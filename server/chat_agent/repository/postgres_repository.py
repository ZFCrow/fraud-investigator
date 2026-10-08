from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, and_

from server.chat_agent.schemas import AgentTrace, WorkflowAgentTrace
from server.chat_agent.repository.SQLModels import agent_trace
from server.chat_agent.repository.repository import IChatRepository

import logging
class PostGresChatRepository(IChatRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert_trace(self, trace: AgentTrace):
        dao = self._to_sql_model(trace)
        self.session.add(dao)
        await self.session.commit()

    def _to_sql_model(self, trace: AgentTrace) -> agent_trace:
        # trace may be a plain AgentTrace or a WorkflowAgentTrace (adds `steps`) --
        # getattr rather than isinstance so this doesn't need to import/know about
        # the subclass specifically, just whether the attribute is there. Mirrors
        # _to_domain below (DAO -> domain model); this is the domain model -> DAO
        # direction, and any future per-pipeline DTO field follows the same shape:
        # add the column to SQLModels.agent_trace, then read it here with getattr.
        steps = getattr(trace, "steps", None)
        return agent_trace(
            id=trace.id,
            session_id=trace.session_id,
            input=trace.input,
            output=trace.output,
            tool_calls=[tc.model_dump(mode="json") for tc in trace.tool_calls] if trace.tool_calls else None,
            steps=[s.model_dump(mode="json") for s in steps] if steps else None,
            created_at=trace.created_at,
            agent_prompt_id=trace.agent_prompt_id
        )

    async def get_trace_by_session_id(self, session_id: str) -> list[AgentTrace]:
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        
        stmt = select(agent_trace).where(
            and_(
                agent_trace.session_id == session_id,
                agent_trace.created_at >= one_hour_ago
                )
        )

        result = await self.session.execute(stmt)
        traces = result.scalars().all()
        
        logging.info(f"\n📝 type of traces is : {type(traces)}")
        logging.info(f"\n📝 traces are : {traces}"  )
        return [self._to_domain(trace) for trace in traces]

    def _to_domain(self, dao: agent_trace) -> AgentTrace:
        base = AgentTrace.model_validate(dao, from_attributes=True)
        # `steps or []` covers rows with no steps recorded (NULL, not an empty list) --
        # WorkflowAgentTrace.steps is required, so a bare None would fail validation.
        return WorkflowAgentTrace(**base.model_dump(), steps=dao.steps or [])
