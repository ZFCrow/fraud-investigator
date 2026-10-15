from abc import ABC, abstractmethod

from server.chat_agent.tools.WebSearch.schemas import WebSearchResult


class IWebSearchRepository(ABC):

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[WebSearchResult]:
        """
        Searches the public web and returns the most relevant pages, best first.
        The query is sent to a third party: it must never contain store data (customer
        names, emails, devices, IPs, cards, order ids).
        """
        ...
