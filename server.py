from __future__ import annotations

import os
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dotenv import load_dotenv

from langchain_openai import AzureChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel

# Modern MCP client supporting multiple transports / subprocesses
from langchain_mcp_adapters.client import MultiServerMCPClient

from CalendlyWorkflow import run_calendly_workflow

import httpx, asyncio, json, traceback

load_dotenv()

logger = logging.getLogger("CalendlyAPI")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

app = FastAPI(title="Calendly Scheduling API", version="0.1.0")

# Enable permissive CORS (adjust for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Globals (may be populated lazily)
mcp_client: Optional[MultiServerMCPClient] = None
llm: Optional[BaseChatModel] = None

# Async lock to prevent race conditions on cold starts
_init_lock = asyncio.Lock()


async def ensure_mcp_client() -> MultiServerMCPClient:
    """Return a ready MultiServerMCPClient, initialising it once lazily.

    This avoids the race between FastAPI lifespan startup and the first
    request in a Vercel Serverless Function.
    """

    global mcp_client, llm  # noqa: PLW0603

    if mcp_client is not None:
        return mcp_client

    async with _init_lock:
        # Re-check inside the lock – another coroutine may have set it.
        if mcp_client is not None:
            return mcp_client

        # Get the path to locally installed calendly-mcp-server
        calendly_server_path = os.getenv(
            "CALENDLY_MCP_PATH",
            os.path.join(os.path.dirname(__file__), "calendly-mcp-server")
        )

        # Build MCP config for stdio transport (local installation)
        mcp_config = {
            "calendly": {
                "transport": "stdio",
                "command": "node",
                "args": [f"{calendly_server_path}/dist/index.js"],
                "env": {
                    "CALENDLY_API_KEY": os.getenv("CALENDLY_API_KEY", ""),
                    "CALENDLY_CLIENT_ID": os.getenv("CALENDLY_CLIENT_ID", ""),
                    "CALENDLY_CLIENT_SECRET": os.getenv("CALENDLY_CLIENT_SECRET", ""),
                    "CALENDLY_REFRESH_TOKEN": os.getenv("CALENDLY_REFRESH_TOKEN", ""),
                    "CALENDLY_USER_URI": os.getenv("CALENDLY_USER_URI", ""),
                    "CALENDLY_ORGANIZATION_URI": os.getenv("CALENDLY_ORGANIZATION_URI", ""),
                }
            }
        }

        logger.info("Initialising Calendly MCP client lazily …")
        new_client = MultiServerMCPClient(mcp_config)

        try:
            tools = await new_client.get_tools()
            logger.info("Loaded Calendly tools: %s", [t.name for t in tools])
        except Exception:
            logger.exception("Calendly MCP initialisation failed")
            raise HTTPException(status_code=503, detail="Failed to connect to Calendly MCP server.")

        mcp_client = new_client

        # Lazy LLM initialisation too (Azure variables might only exist in prod)
        if llm is None and os.getenv("AZURE_OPENAI_ENDPOINT"):
            llm = AzureChatOpenAI(
                deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                api_version=os.getenv("OPENAI_API_VERSION", "2023-12-01-preview"),
            )

        return mcp_client


class QuestionRequest(BaseModel):
    question: str


class AnswerResponse(BaseModel):
    answer: str


@app.on_event("startup")
async def startup_event() -> None:
    """Launch Calendly MCP server and prepare LLM once when the API starts."""

    global mcp_client, llm

    logger.info("Starting Calendly MCP server (FastAPI startup)…")

    # Get the path to locally installed calendly-mcp-server
    calendly_server_path = os.getenv(
        "CALENDLY_MCP_PATH",
        os.path.join(os.path.dirname(__file__), "calendly-mcp-server")
    )

    # ------------------------------------------------------------------
    # 1. Configure & launch Calendly MCP server via MultiServerMCPClient
    # ------------------------------------------------------------------
    mcp_config = {
        "calendly": {
            "transport": "stdio",
            "command": "node",
            "args": [f"{calendly_server_path}/dist/index.js"],
            "env": {
                "CALENDLY_API_KEY": os.getenv("CALENDLY_API_KEY", ""),
                "CALENDLY_CLIENT_ID": os.getenv("CALENDLY_CLIENT_ID", ""),
                "CALENDLY_CLIENT_SECRET": os.getenv("CALENDLY_CLIENT_SECRET", ""),
                "CALENDLY_REFRESH_TOKEN": os.getenv("CALENDLY_REFRESH_TOKEN", ""),
                "CALENDLY_USER_URI": os.getenv("CALENDLY_USER_URI", ""),
                "CALENDLY_ORGANIZATION_URI": os.getenv("CALENDLY_ORGANIZATION_URI", ""),
            }
        }
    }

    logger.info("DEBUG ENV: CALENDLY_API_KEY=%s | CALENDLY_USER_URI=%s",
            "***" if os.getenv("CALENDLY_API_KEY") else "NOT SET", 
            os.getenv("CALENDLY_USER_URI"))

    mcp_client = MultiServerMCPClient(mcp_config)

    # Ensure tools are loaded (spawns subprocesses when necessary)
    try:
        tools = await mcp_client.get_tools()
        logger.info("Loaded Calendly tools: %s", [t.name for t in tools])
    except Exception:
        logger.exception("Calendly MCP initialisation failed")
        return          # keep mcp_client == None so handler still returns 503

    # 2. Optional LLM
    if os.getenv("AZURE_OPENAI_ENDPOINT"):
        llm = AzureChatOpenAI(
            deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("OPENAI_API_VERSION", "2023-12-01-preview"),
        )


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global mcp_client
    if mcp_client is not None:
        logger.info("Shutting down Calendly MCP client …")
        # MultiServerMCPClient implements async cleanup via __aexit__
        try:
            await mcp_client.__aexit__(None, None, None)
        finally:
            mcp_client = None
            logger.info("Cleanup complete.")


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "message": "Calendly Scheduling API is running",
        "version": "0.1.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check."""
    return {
        "status": "ok",
        "mcp_client": "connected" if mcp_client is not None else "not initialized",
        "llm": "available" if llm is not None else "not configured"
    }


@app.post("/calendly/ask", response_model=AnswerResponse)
async def ask_calendly(question_req: QuestionRequest) -> AnswerResponse:
    if not question_req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    client = await ensure_mcp_client()

    try:
        answer = await run_calendly_workflow(
            mcp_client=client,
            user_question=question_req.question,
            llm=llm,
        )
        return AnswerResponse(answer=answer)
    except Exception as e:
        logger.exception("Error during workflow execution: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

