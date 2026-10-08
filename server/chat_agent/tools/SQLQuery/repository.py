from abc import ABC, abstractmethod


class IStoreQueryRepository(ABC): 

    @abstractmethod
    def execute_sql(self, sql: str):
        """
        Execute a raw SQL query against the database and return the results."""
        ... 