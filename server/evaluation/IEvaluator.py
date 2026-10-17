from abc import ABC, abstractmethod
from llama_index.core.llms import ChatMessage
from server.chat_agent.schemas import AgentTrace

from server.evaluation.schemas import EvaluationResult

class IEvaluator(ABC):
    @abstractmethod
    async def evaluate(
        self,
        og_user_input: str,
        trace: AgentTrace,
        chat_history: list[ChatMessage]
    ) -> EvaluationResult:

        """
        Evaluate the agent's response for a single turn.

        :param og_user_input: The original user input.
        :param trace: The current turn's AgentTrace (input, output, tool_calls).
        :param chat_history: Prior turns as ChatMessage list, oldest first.
        :param expected_answer: Ground-truth reference answer, when known (benchmark runs
            only — live traffic has no labeled "correct" answer). Implementations that
            don't compare against a reference answer should accept and ignore it.
        :return: Dict with scores and reasoning.
        """
        ...
