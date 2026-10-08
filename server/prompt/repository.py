import uuid
from abc import ABC, abstractmethod
from typing import Optional

from server.prompt.enums import PROMPTTYPE
from server.prompt.schemas import Prompt


class IPromptRepository(ABC):
    """
    Interface for the Prompt Repository — versioned storage for prompt text that
    used to be hardcoded (the workflow step prompts, EVAL_PROMPT), so the reflector can
    propose and promote new prompt versions without a code deploy.
    """

    @abstractmethod
    async def insert_prompt(self, prompt: Prompt) -> Prompt:
        """
        Insert a new prompt version. Same shape as insert_evaluation_result /
        insert_trace elsewhere — takes the domain model, not exploded fields.

        prompt.version is ignored: the repository always computes the real value
        (current max version for this type + 1, or 1 if none exist yet) and
        overwrites whatever was set on the input. id/created_at are trusted as
        given, same as every other insert_* in this codebase. prompt.is_active
        is respected — if True, whatever was previously active for this type is
        deactivated in the same transaction as the insert.

        Args:
            prompt: The prompt to insert. Construct it with just text/type/
                is_active set (or is_active defaulted to False for a reflector
                candidate awaiting validation) — version can be left at its
                default, it plays no role in the insert.

        Returns:
            The persisted Prompt, with the real version populated.
        """

    @abstractmethod
    async def get_active_prompt(self, type: PROMPTTYPE) -> Optional[Prompt]:
        """
        Fetch the prompt currently in effect for `type` (the row with
        is_active=True). Runtime consumers (the agent pipeline, the evaluator) call
        this instead of reading a hardcoded prompt constant.

        Args:
            type: Which system's active prompt to fetch.

        Returns:
            The active Prompt, or None if no prompt has ever been activated for
            this type — callers should fall back to a hardcoded default in that case.
        """

    @abstractmethod
    async def get_prompt_by_id(self, prompt_id: uuid.UUID) -> Optional[Prompt]:
        """
        Fetch one specific prompt version by id, active or not. Distinct from
        get_active_prompt: the reflector needs the exact judge prompt a past
        evaluation run used (EvaluationResult.evaluator_prompt_id), which may no
        longer be the active one.

        Args:
            prompt_id: id of the prompt row to fetch.

        Returns:
            The matching Prompt, or None if no prompt exists with that id.
        """

    @abstractmethod
    async def activate_prompt(self, prompt_id: uuid.UUID) -> None:
        """
        Mark one prompt row as the active version for its type, atomically
        deactivating whatever was previously active for that same type.

        Args:
            prompt_id: id of the prompt row to activate.
        """

    @abstractmethod
    async def retrieve_prompts(self, type: Optional[PROMPTTYPE] = None, limit: int = 200) -> list[Prompt]:
        """
        Fetch prompt version history, newest first, optionally scoped to one type.

        Args:
            type: Restrict to this prompt type, or None for all types.
            limit: Maximum number of rows to return.
        """
