from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class IStoreQueryRepository(ABC):

    @abstractmethod
    async def get_data_as_of(self) -> Optional[datetime]:
        """
        When the store's data ends: the latest session activity, or None when the store is
        empty. The data is a fixed snapshot, so this -- not the real clock -- is "now" for
        every question.
        """
        ...

    @abstractmethod
    def execute_sql(self, sql: str):
        """
        Execute a raw SQL query against the store database, as a user that can only read,
        and return the rows. A query the database rejects or fails raises ToolError tagged
        with how: blocked (not permitted), or an error type (invalid query, timeout, runtime).
        """
        ... 