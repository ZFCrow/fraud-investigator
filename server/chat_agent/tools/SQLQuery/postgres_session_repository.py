# repository.py
from sqlalchemy import  text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import timedelta, timezone
import logging
from server.chat_agent.tools.SQLQuery.repository import IStoreQueryRepository

class PostgresStoreQueryRepository(IStoreQueryRepository): 
    def __init__(self, 
                 session: AsyncSession):
        self.tz = timezone(timedelta(hours=8))
        self.session = session
    
    #! this is for the agent to pass in a select query
    async def execute_sql(self, sql: str):
        try:
            result = await self.session.execute(
            text(sql)
        )
            return result.mappings().all()
        except Exception as e:
            await self.session.rollback()  # rollback on error 
            logging.error(f"Error executing SQL: {str(e)}") 
            raise


