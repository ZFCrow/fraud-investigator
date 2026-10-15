import httpx

from server.chat_agent.tools.WebSearch.repository import IWebSearchRepository
from server.chat_agent.tools.WebSearch.schemas import WebSearchResult
from server.chat_agent.tools.exceptions import ToolError
from server.chat_agent.tools.enums import ToolErrorType


class TavilyWebSearchRepository(IWebSearchRepository):
    """Tavily's /search endpoint, called directly over HTTP (no SDK needed for one call)."""

    def __init__(self, api_key: str, base_url: str = "https://api.tavily.com", timeout: float = 20.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[WebSearchResult]:
        if not self.api_key:
            raise ToolError("Web search is not configured (TAVILY_API_KEY is empty).")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/search",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "query": query,
                        "max_results": max_results,
                        "search_depth": "basic",
                        "topic": "general",
                        "include_answer": False,
                    },
                )
                response.raise_for_status()
        except httpx.TimeoutException as e:
            raise ToolError(f"Web search timed out: {e}", error_type=ToolErrorType.TIMEOUT) from e
        except httpx.HTTPError as e:
            raise ToolError(f"Web search failed: {e}") from e

        return [WebSearchResult.model_validate(r) for r in response.json().get("results", [])]
