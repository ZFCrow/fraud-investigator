from pydantic import BaseModel, Field


class WebSearchResult(BaseModel):
    """One public page returned for a fraud-pattern search."""
    title: str
    url: str
    content: str = Field(..., description="The search provider's extract of the page relevant to the query.")
    score: float = Field(default=0.0, description="The provider's relevance score, 0-1.")

    def to_text(self) -> str:
        """The result as the model reads it: the URL stays verbatim so the answer can cite it."""
        return f"[{self.score:.2f}] {self.title}\nURL: {self.url}\n{self.content}"
