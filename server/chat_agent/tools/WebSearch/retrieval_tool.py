import re

from server.chat_agent.schemas import ToolCall
from server.chat_agent.tools.tool import AgentTool
from server.chat_agent.tools.enums import ToolErrorType, ToolName
from server.chat_agent.tools.exceptions import ToolError
from server.chat_agent.tools.WebSearch.repository import IWebSearchRepository
from server.chat_agent.tools.WebSearch.schemas import WebSearchResult


# Store identifiers that must never leave the system in a third-party search query. Names
# can't be caught by pattern, so the args prompt forbids them too; this is the backstop.
STORE_IDENTIFIER_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "ip address": re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),
    "device id": re.compile(r"\bdev-[0-9a-f]{6,}\b", re.IGNORECASE),
    "card fingerprint": re.compile(r"\bcard_[0-9a-f]{6,}\b", re.IGNORECASE),
    "address id": re.compile(r"\baddr-[0-9a-f]{6,}\b", re.IGNORECASE),
    "session id": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE),
}


class FraudPatternSearchTool(AgentTool):
    """
    Searches the public web for a fraud pattern the store data showed, so the answer can say
    whether it matches a known scheme (card testing, refund abuse, triangulation...) and cite
    current sources. Only a generic description of the pattern is ever sent out.
    """
    def __init__(self,
                 repo: IWebSearchRepository,
                 tools_called: list[ToolCall] = None,
                 ):
        super().__init__(ToolName.SEARCH_FRAUD_PATTERNS, tools_called)
        self.repo = repo

    async def __call__(self, query: str, max_results: int = 5) -> list[str]:
        leaked: list[str] = [kind for kind, pattern in STORE_IDENTIFIER_PATTERNS.items() if pattern.search(query)]
        if leaked:
            # rejected before anything is sent, so it is repaired like an invalid SQL query
            raise ToolError(
                f"The search query contains store data ({', '.join(leaked)}) and was not sent. "
                f"Rewrite it as a generic description of the behaviour, with no identifiers.",
                error_type=ToolErrorType.INVALID_QUERY,
            )

        results: list[WebSearchResult] = await self.repo.search(query, max_results=max_results)
        return [r.to_text() for r in results]
