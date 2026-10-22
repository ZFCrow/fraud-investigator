# repository.py
from sqlalchemy import  text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
from typing import Optional
import logging
from server.chat_agent.tools.SQLQuery.repository import IStoreQueryRepository
from server.chat_agent.tools.enums import ToolErrorType, ToolStatus
from server.chat_agent.tools.exceptions import ToolError

# insufficient_privilege, read_only_sql_transaction. 42501 sits in the same SQLSTATE class
# as the invalid-query codes, so it has to be checked first.
_BLOCKED_SQLSTATES = ("42501", "25006")
_QUERY_CANCELED = "57014"  # what the reader role's statement_timeout raises


class PostgresStoreQueryRepository(IStoreQueryRepository):
    """Runs the agent's SQL. The session it is given connects as the read-only role
    (settings.DB_READER_USER), so the database itself is what stops a write."""
    def __init__(self,
                 session: AsyncSession):
        self.tz = timezone(timedelta(hours=8))
        self.session = session

    async def get_data_as_of(self) -> Optional[datetime]:
        return await self.session.scalar(
            text("SELECT max(coalesce(ended_at, started_at)) FROM shop.sessions")
        )

    #! this is for the agent to pass in a select query
    async def execute_sql(self, sql: str):
        try:
            result = await self.session.execute(
            text(sql)
        )
            return result.mappings().all()
        except DBAPIError as e:
            await self.session.rollback()  # rollback on error
            logging.error(f"Error executing SQL: {str(e)}")
            raise self._tool_error(e, sql) from e
        except Exception as e:
            await self.session.rollback()  # rollback on error
            logging.error(f"Error executing SQL: {str(e)}")
            raise

    @staticmethod
    def _error_location(e: DBAPIError, sql: str) -> str:
        """Where in the query Postgres failed: the line it points at, and its hint if any.
        The bare message ("missing FROM-clause entry for table "o"") doesn't say which of
        several CTEs is wrong, and without the line the repair step resubmitted the same
        query unchanged."""
        pg_error = e.orig.__cause__  # the asyncpg exception under SQLAlchemy's DBAPI wrapper
        position: Optional[str] = getattr(pg_error, "position", None)
        hint: Optional[str] = getattr(pg_error, "hint", None)
        location = ""
        if position and position.isdigit():
            line_no: int = sql.count("\n", 0, int(position) - 1) + 1
            location = f"\nAt line {line_no}: {sql.splitlines()[line_no - 1].strip()}"
        return location + (f"\nHint: {hint}" if hint else "")

    @classmethod
    def _tool_error(cls, e: DBAPIError, sql: str) -> ToolError:
        """Postgres says how a statement failed in its SQLSTATE code. Class 42 (syntax error
        or access rule violation) is raised while parsing/planning, before any row is read."""
        sqlstate: str = e.orig.sqlstate or ""
        message = str(e.orig)
        if sqlstate in _BLOCKED_SQLSTATES:
            return ToolError(message, status=ToolStatus.BLOCKED, error_type=None)
        if sqlstate.startswith("42"):
            return ToolError(message + cls._error_location(e, sql), error_type=ToolErrorType.INVALID_QUERY)
        if sqlstate == _QUERY_CANCELED:
            return ToolError(message, error_type=ToolErrorType.TIMEOUT)
        return ToolError(message, error_type=ToolErrorType.RUNTIME)
