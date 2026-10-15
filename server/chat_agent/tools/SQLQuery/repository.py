from abc import ABC, abstractmethod


class IStoreQueryRepository(ABC): 

    @abstractmethod
    def execute_sql(self, sql: str):
        """
        Execute a raw SQL query against the store database, as a user that can only read,
        and return the rows. A query the database rejects or fails raises ToolError tagged
        with how: blocked (not permitted), or an error type (invalid query, timeout, runtime).
        """
        ... 