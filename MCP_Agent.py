from typing import Any, Dict, Literal, List

from pydantic import BaseModel
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

class MCP_Args(BaseModel):
    command: str
    args: List[str]
    transport: Literal["stdio", "sse", "websocket", "streamable_http"]

class Tool_Args(BaseModel):
    method: Literal["include", "exclude"]
    tools: List[str]

class MCP_Agent:
    """Thin wrapper that spawns an MCP client and constructs a ReAct agent over its tools."""

    def __init__(
        self,
        llm: BaseChatModel | None,
        mcp_args: Dict[str, MCP_Args],
        tool_args: Tool_Args | None = None,
    ):
        self.agent = None
        self.mcp_client: MultiServerMCPClient | None = None
        self.llm = llm
        self.mcp_args = mcp_args
        self.tool_args = tool_args

    async def initialize(self):
        """Launch the MCP server(s) and build a ReAct agent over their tools."""

        # Create the client first – this starts any configured sub-processes
        new_mcp_client = MultiServerMCPClient(self.mcp_args)
        await new_mcp_client.__aenter__()
        self.mcp_client = new_mcp_client

        # Fetch tools exposed by all configured servers
        tools = new_mcp_client.get_tools()
        print(tools)

        if self.tool_args is not None:
            predicate = (
                (lambda tool: tool in self.tool_args.tools)
                if self.tool_args.method == "include"
                else (lambda tool: tool not in self.tool_args.tools)
            )
            tools = [tool for tool in tools if predicate(tool.name)]

        # Build a ReAct agent only if an LLM instance is supplied
        if self.llm is not None:
            self.agent = create_react_agent(self.llm, tools)

    async def invoke(self, input: Dict[str, Any] | Any) -> str:
        """Invoke the ReAct agent and return the assistant's final message content."""

        if self.agent is None:
            await self.initialize()

        if self.agent is None:
            return "Agent not initialised - missing LLM?"

        response = await self.agent.ainvoke(input)
        ai_messages = [msg for msg in response["messages"] if isinstance(msg, AIMessage)]
        if ai_messages:
            return ai_messages[-1].content

        return "No AI message found in response"

    async def cleanup_resources(self):
        await self.mcp_client.__aexit__(None, None, None)
        self.mcp_client = None
        self.agent = None

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup_resources()

