from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
from llama_index.core.llms import ChatMessage
from server.chat_agent.schemas import AgentTrace

from server.evaluation.schemas import EvaluationResult
from server.prompt.schemas import Prompt

class IEvaluator(ABC):
    @abstractmethod
    async def evaluate(
        self,
        og_user_input: str,
        trace: AgentTrace,
        prompt: Prompt,
        chat_history: list[ChatMessage],
        data_as_of: Optional[datetime] = None,
    ) -> EvaluationResult:

        """
        Evaluate the agent's response for a single turn.

        :param og_user_input: The original user input.
        :param trace: The current turn's AgentTrace (input, output, tool_calls).
        :param prompt: The judge prompt version to evaluate with.
        :param chat_history: Prior turns as ChatMessage list, oldest first.
        :param data_as_of: When the store's data ends. The agent answers every question as
            if asked then, so relative periods must be judged against it, not the real date.
        :param expected_answer: Ground-truth reference answer, when known (benchmark runs
            only — live traffic has no labeled "correct" answer). Implementations that
            don't compare against a reference answer should accept and ignore it.
        :return: Dict with scores and reasoning.
        """
        ...
