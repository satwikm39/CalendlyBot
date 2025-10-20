from typing import Optional, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_mcp_adapters.client import MultiServerMCPClient

# Local import to avoid circular issues if MCP_Agent isn't used in a particular workflow.
try:
    from MCP_Agent import MCP_Agent  # type: ignore
except ImportError:  # Fallback when MCP_Agent not yet available
    MCP_Agent = None  # type: ignore


class BaseSchema(TypedDict):
    """Common typed-dict fields shared by workflow state objects.

    Keeps references to the MCP client, optional LLM instance and (optionally)
    an agent wrapper so that nodes can reuse them without re-initialising.
    """

    mcp_agent: Optional[MCP_Agent]
    llm: Optional[BaseChatModel]
    mcp_client: Optional[MultiServerMCPClient]
    error: str
    output: str

