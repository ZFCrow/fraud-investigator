import uuid
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server.prompt.enums import PROMPTTYPE
from server.prompt.repository import IPromptRepository
from server.prompt.schemas import Prompt
# Aliased: insert_prompt below takes a `prompt: Prompt` argument, which would
# shadow the bare ORM class name for the rest of that method.
from server.prompt.SQLModels import prompt as PromptRow

from server.prompt.prompts import tracked_prompt

def _to_domain(row: PromptRow) -> Prompt:
    return Prompt(
        id=row.id,
        text=row.text,
        type=PROMPTTYPE(row.type),
        version=row.version,
        is_active=row.is_active,
        created_at=row.created_at,
    )


class PostgresPromptRepository(IPromptRepository):

    def __init__(self, session: AsyncSession):
        self.session = session

    async def setup(
            self
            ) -> None:
        """
        function should be called once at the start of the app 
        to ensure that there is an active prompt for each prompt type. 
        """
        # check if theres an active prompt for each type, if not create one with default text 
        for prompt_type in PROMPTTYPE: 
            prompt = await self.get_active_prompt(prompt_type) 

            if not prompt:
                default_prompt_text = tracked_prompt.get(prompt_type, "default_text")

                new_prompt = Prompt( 
                    id=uuid.uuid4(),
                    text=default_prompt_text,
                    type=prompt_type,
                    version=1,
                    is_active=True,
                ) 
                await self.insert_prompt(new_prompt) 
             


    async def insert_prompt(self, prompt: Prompt) -> Prompt:
        # prompt.version is deliberately ignored — computed fresh here instead.
        current_max = await self.session.scalar(
            select(func.max(PromptRow.version)).where(PromptRow.type == prompt.type.value)
        )
        next_version = (current_max or 0) + 1

        if prompt.is_active:
            # Deactivate whatever is currently active for this type in the same
            # transaction as the insert/commit below, so there's never a moment —
            # not even across a crash — with two active rows for one type.
            await self.session.execute(
                update(PromptRow)
                .where(PromptRow.type == prompt.type.value, PromptRow.is_active.is_(True))
                .values(is_active=False)
            )

        row = PromptRow(
            id=prompt.id,
            text=prompt.text,
            type=prompt.type.value,
            version=next_version,
            is_active=prompt.is_active,
            created_at=prompt.created_at,
        )
        self.session.add(row)
        await self.session.commit()

        return _to_domain(row)

    async def get_active_prompt(self, type: PROMPTTYPE) -> Optional[Prompt]:
        stmt = select(PromptRow).where(PromptRow.type == type.value, PromptRow.is_active.is_(True))
        row = await self.session.scalar(stmt)
        return _to_domain(row) if row is not None else None

    async def get_prompt_by_id(self, prompt_id: uuid.UUID) -> Optional[Prompt]:
        row = await self.session.get(PromptRow, prompt_id)
        return _to_domain(row) if row is not None else None

    async def activate_prompt(self, prompt_id: uuid.UUID) -> None:
        target = await self.session.get(PromptRow, prompt_id)
        if target is None:
            raise ValueError(f"No prompt found with id {prompt_id}")

        # Scope the deactivation to the target's own type — other types' active
        # rows must be untouched.
        await self.session.execute(
            update(PromptRow)
            .where(PromptRow.type == target.type, PromptRow.is_active.is_(True), PromptRow.id != target.id)
            .values(is_active=False)
        )
        target.is_active = True
        await self.session.commit()

    async def retrieve_prompts(self, type: Optional[PROMPTTYPE] = None, limit: int = 200) -> list[Prompt]:
        stmt = select(PromptRow).order_by(PromptRow.created_at.desc()).limit(limit)
        if type is not None:
            stmt = stmt.where(PromptRow.type == type.value)

        result = await self.session.execute(stmt)
        return [_to_domain(row) for row in result.scalars().all()]

    async def update_prompt(self, prompt: Prompt) -> None:
        """
        Update an existing prompt in the database. The prompt is identified by its id.
        Only the text, is_active, gap_analysis_reason, and root_cause_analysis_reason fields can be updated.
        The version and type fields are immutable once set.

        Args:
            prompt: The prompt to update. It must have a valid id corresponding to an existing prompt in the database. 
        
        """
        existing_prompt = await self.session.get(PromptRow, prompt.id)
        if not existing_prompt:
            raise ValueError(f"No prompt found with id {prompt.id}")

        # Update the fields that can be changed
        existing_prompt.gap_analysis_reason = prompt.gap_analysis_reason
        existing_prompt.root_cause_analysis_reason = prompt.root_cause_analysis_reason

        # update text
        existing_prompt.text = prompt.text 
        await self.session.commit() 