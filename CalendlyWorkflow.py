import os
import logging
from typing import Literal, List, Dict, Any

from dotenv import load_dotenv

from langgraph.graph import END, StateGraph
from langgraph.graph.graph import CompiledGraph
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import AzureChatOpenAI

# Local imports
from BaseSchema import BaseSchema
from langchain_mcp_adapters.client import MultiServerMCPClient
import json as _json

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("CalendlyWorkflow")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")

load_dotenv()


class CalendlyState(BaseSchema):
    """State for the Calendly scheduling workflow."""

    intent: Literal["calendly scheduling"]
    user_question: str  # The incoming natural-language question

    # Tools available in MCP (populated once)
    available_tools: List[str] = []

    # Plan produced by the LLM classifier
    plan: Dict[str, Any] = {}

    # For storing Calendly data
    calendly_data: str = ""

    # For action results
    mcp_result: Any = None

    # Intermediate / output fields
    llm_answer: str = ""
    output: str = ""


# ---------------------------------------------------------------------------
# Node callbacks
# ---------------------------------------------------------------------------

# 1. Fetch and cache tool list ------------------------------------------------

async def cache_tools(state: CalendlyState) -> CalendlyState:  # type: ignore[arg-type]
    if state.get("available_tools"):
        return state

    client: MultiServerMCPClient = state["mcp_client"]
    tool_objs = await client.get_tools()
    state["available_tools"] = [t.name for t in tool_objs]
    # cache full objects for later use
    state["_tool_map"] = {t.name: t for t in tool_objs}
    logger.info("Available Calendly MCP tools: %s", state["available_tools"])
    return state


# 2. Classify user intent & build plan ---------------------------------------

async def classify_question(state: CalendlyState) -> CalendlyState:  # type: ignore[arg-type]
    """Use the LLM to decide what Calendly action the user wants and construct appropriate arguments."""

    llm: BaseChatModel | None = state["llm"]
    if llm is None:
        # Fallback: treat everything as get current user
        state["plan"] = {"action": "get_current_user", "params": {}}
        return state

    tools_list = ", ".join(state.get("available_tools", []))

    prompt = (
        "You are a Calendly assistant. Using the following MCP tools: "
        f"{tools_list}.\n\n"
        "Analyze the USER MESSAGE and output ONLY valid JSON with this schema:\n"
        "{\n"
        "  action: string,           // One of the available tool names\n"
        "  params: object            // Parameters required for that tool\n"
        "}\n\n"
        "Available actions and their parameters:\n"
        "- get_current_user: no parameters\n"
        "- list_events: { user_uri?, organization_uri?, status?, max_start_time?, min_start_time?, count? }\n"
        "- get_event: { event_uuid: string }\n"
        "- list_event_invitees: { event_uuid: string, status?, email?, count? }\n"
        "- cancel_event: { event_uuid: string, reason?: string }\n"
        "- list_organization_memberships: { user_uri?, organization_uri?, email?, count? }\n"
        "- send_booking_invitation: { to_email: string, to_name?: string, event_name: string, event_duration: number, available_days: array, booking_link: string, custom_message?: string }\n"
        "- create_and_invite_workflow: { event_name: string, duration: number, availability_days: array, invitee_email: string, invitee_name?: string, event_description?: string, custom_message?: string }\n"
        "- create_one_off_event_type: { event_name: string, duration: number, availability_days: array, invitee_email: string, invitee_name?: string, event_description?: string, custom_message?: string }\n\n"
        "Rules:\n"
        "- Choose the most appropriate action based on user intent.\n"
        "- NEVER wrap objects in strings; output real JSON.\n"
        "- If dates are mentioned, convert them to ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ).\n"
        "- For list operations, default count to 20 if not specified.\n"
    )

    user_question = state["user_question"]
    resp = await llm.ainvoke(prompt + f"\nUSER MESSAGE:\n{user_question}\n")

    try:
        plan = _json.loads(resp.content)
    except Exception:
        logger.warning("Could not parse LLM plan, defaulting to get_current_user. Response: %s", resp.content)
        plan = {"action": "get_current_user", "params": {}}

    state["plan"] = plan
    logger.debug("LLM PLAN → %s", _json.dumps(plan, indent=2))
    logger.debug("Raw LLM content → %s", resp.content)
    return state


# 3. Execute Calendly action -------------------------------------------------

async def execute_action(state: CalendlyState) -> CalendlyState:  # type: ignore[arg-type]
    client: MultiServerMCPClient = state["mcp_client"]
    plan = state["plan"]
    
    action = plan.get("action", "get_current_user")
    params = plan.get("params", {})
    # For create_one_off_event_type, fully map raw LLM output into Calendly API schema
    if action == "create_one_off_event_type":
        raw = params or {}
        name = raw.get("event_name") or raw.get("name")
        host = raw.get("host") or os.getenv("CALENDLY_USER_URI")
        co_hosts = raw.get("co_hosts") or []
        duration = raw.get("duration")
        timezone = raw.get("timezone") or os.getenv("CALENDLY_TIMEZONE") or "UTC"
        # Build date_setting
        if raw.get("date_setting") and isinstance(raw.get("date_setting"), dict):
            date_setting = raw["date_setting"]
        else:
            days = raw.get("availability_days") or []
            date_setting = {
                "type": "date_range",
                "start_date": days[0] if days else None,
                "end_date": days[-1] if len(days) > 1 else (days[0] if days else None)
            }
        # Build location
        if raw.get("location") and isinstance(raw.get("location"), dict):
            location = raw["location"]
        else:
            location = {
                "kind": raw.get("location_kind") or "physical",
                "location": raw.get("location_details") or raw.get("event_description") or "",
                "additional_info": raw.get("event_description") or ""
            }
        params = {
            "name": name,
            "host": host,
            "co_hosts": co_hosts,
            "duration": duration,
            "timezone": timezone,
            "date_setting": date_setting,
            "location": location
        }
    # Log the action and parameters before invoking the tool
    logger.info("Executing Calendly action '%s' with params: %s", action, params)

    # Get the tool mapping
    tools_map = state.get("_tool_map") or {t.name: t for t in await client.get_tools()}
    
    # Find the tool
    tool_obj = tools_map.get(action)
    if tool_obj is None:
        state["calendly_data"] = f"Tool '{action}' not available"
        return state

    try:
        # Execute the tool
        result = await tool_obj.ainvoke(params)
        state["calendly_data"] = _json.dumps(result, indent=2) if not isinstance(result, (str, bytes)) else str(result)
        state["mcp_result"] = result
        
        logger.info("Executed Calendly action: %s", action)
    except Exception as e:
        logger.exception("Error executing Calendly action: %s", e)
        # Log the parameters and raw exception for debugging
        logger.error("Failed action '%s' with params: %s", action, params)
        logger.error("Exception details: %s", e)
        if hasattr(e, 'args'):
            logger.error("Exception args: %s", e.args)
        state["calendly_data"] = f"Error: {str(e)}"
        state["error"] = str(e)

    return state


# 4. Generate response --------------------------------------------------------

async def generate_response(state: CalendlyState) -> CalendlyState:  # type: ignore[arg-type]
    """Ask the LLM to craft the final user-facing answer based on Calendly results."""

    llm = state["llm"]
    if llm is None:
        state["output"] = str(state.get("calendly_data"))
        return state

    action = state["plan"].get("action", "get_current_user")

    prompt = (
        "You are a Calendly scheduling assistant. Using ONLY the data below, "
        "provide a helpful and clear answer to the user's question.\n\n"
        f"USER QUESTION:\n{state['user_question']}\n\n"
        f"ACTION PERFORMED:\n{action}\n\n"
        f"CALENDLY DATA (JSON):\n{state['calendly_data']}\n\n"
        "Format your response in a user-friendly way:\n"
        "- For events: show date, time, duration, and invitees\n"
        "- For user info: show name, email, and organization\n"
        "- For errors: explain what went wrong and suggest next steps\n"
        "- Be concise but informative\n"
    )

    resp = await llm.ainvoke(prompt)
    state["output"] = resp.content.strip()
    return state


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_calendly_graph() -> CompiledGraph:  # noqa: D401
    g = StateGraph(CalendlyState)

    g.add_node("cache_tools", cache_tools)
    g.add_node("classify", classify_question)
    g.add_node("execute", execute_action)
    g.add_node("respond", generate_response)

    g.set_entry_point("cache_tools")

    # Linear flow
    g.add_edge("cache_tools", "classify")
    g.add_edge("classify", "execute")
    g.add_edge("execute", "respond")
    g.add_edge("respond", END)

    return g.compile()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run_calendly_workflow(
    mcp_client: MultiServerMCPClient,
    user_question: str,
    llm: BaseChatModel | None = None,
) -> str:
    graph = build_calendly_graph()

    initial_state: CalendlyState = {
        "mcp_client": mcp_client,
        "llm": llm,
        "intent": "calendly scheduling",
        "user_question": user_question,
        "available_tools": [],
        "plan": {},
        "calendly_data": "",
        "mcp_result": "",
        "output": "",
        "error": "",
        "mcp_agent": None,
    }

    result = await graph.ainvoke(initial_state)
    return result.get("output", "")


# ---------------------------------------------------------------------------
# CLI (for quick manual tests)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import asyncio
    from contextlib import AsyncExitStack

    parser = argparse.ArgumentParser(description="Calendly scheduling workflow")
    parser.add_argument("question", nargs="*", help="Question to ask about Calendly")
    parser.add_argument("--visualize", action="store_true", help="Print ASCII graph and exit")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    args = parser.parse_args()

    question = " ".join(args.question).strip()
    if not question:
        # interactive prompt
        try:
            question = input("❓ Enter your Calendly question: ").strip()
        except EOFError:
            question = ""
    if not question:
        print("No question provided. Exiting.")
        raise SystemExit(1)

    if args.debug:
        logger.setLevel(logging.DEBUG)

    if args.visualize:
        print(build_calendly_graph().get_graph().print_ascii())
        raise SystemExit(0)

    async def main() -> None:
        # Optional LLM
        llm = None
        if os.getenv("AZURE_OPENAI_ENDPOINT"):
            llm = AzureChatOpenAI(
                deployment_name=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                api_version=os.getenv("OPENAI_API_VERSION", "2023-12-01-preview"),
            )

        exit_stack = AsyncExitStack()
        try:
            # -----------------------------------------------------------------
            # 1. Launch Calendly MCP server over stdio (local installation)
            # -----------------------------------------------------------------
            from mcp.client.stdio import stdio_client as _stdio_client
            from mcp import StdioServerParameters as _StdioServerParameters
            
            # Path to locally installed calendly-mcp-server
            calendly_server_path = os.getenv(
                "CALENDLY_MCP_PATH", 
                "/Users/satwik/Developer/hgs/code/calendly-bot/calendly-mcp-server"
            )
            
            server_params = _StdioServerParameters(
                command="node",
                args=[f"{calendly_server_path}/dist/index.js"],
                env={
                    "CALENDLY_API_KEY": os.getenv("CALENDLY_API_KEY", ""),
                    "CALENDLY_CLIENT_ID": os.getenv("CALENDLY_CLIENT_ID", ""),
                    "CALENDLY_CLIENT_SECRET": os.getenv("CALENDLY_CLIENT_SECRET", ""),
                    "CALENDLY_REFRESH_TOKEN": os.getenv("CALENDLY_REFRESH_TOKEN", ""),
                    "CALENDLY_USER_URI": os.getenv("CALENDLY_USER_URI", ""),
                    "CALENDLY_ORGANIZATION_URI": os.getenv("CALENDLY_ORGANIZATION_URI", ""),
                }
            )
            
            read, write = await exit_stack.enter_async_context(_stdio_client(server_params))
            from mcp import ClientSession
            mcp_session = await exit_stack.enter_async_context(ClientSession(read, write))
            logger.info("Initializing Calendly MCP session …")
            await mcp_session.initialize()
            tools_resp = await mcp_session.list_tools()
            logger.info("Calendly MCP server ready; tools: %s", [t.name for t in tools_resp.tools])

            # -----------------------------------------------------------------
            # 2. Run LangGraph workflow
            # -----------------------------------------------------------------
            answer = await run_calendly_workflow(
                mcp_client=mcp_session,
                user_question=question,
                llm=llm,
            )

            print("\n🤖", answer)
        finally:
            logger.info("Cleaning up MCP resources …")
            await exit_stack.aclose()

    asyncio.run(main())

