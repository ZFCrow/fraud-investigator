from server.evaluation.schemas import EvaluationResult
from server.evaluation.SQLModels import evaluation

from abc import ABC, abstractmethod
from sqlalchemy.ext.asyncio import AsyncSession
 
from datetime import timezone, timedelta
from pathlib import Path
import json
import logging


class IEvaluationRepository(ABC):
    """
    Interface for the Evaluation Repository.
    """

    @abstractmethod
    async def insert_evaluation_result(self, evaluation_result: EvaluationResult):
        """
        Insert an evaluation result into the repository.

        Args:
            evaluation_result (EvaluationResult): The evaluation result to be inserted.
        """
        ...

class PostgresEvaluationRepository(IEvaluationRepository):

    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert_evaluation_result(self, evaluation_result: EvaluationResult):
        # Create an instance of the evaluation SQL model
        evaluation_dao = evaluation(
            agent_trace_id=evaluation_result.agent_trace_id,
            evaluator_prompt_id=evaluation_result.evaluator_prompt_id,
            helpfulness_score=evaluation_result.helpfulness.score if evaluation_result.helpfulness else 0,
            helpfulness_reasoning=evaluation_result.helpfulness.reasoning if evaluation_result.helpfulness else "",
            coherence_score=evaluation_result.coherence.score if evaluation_result.coherence else 0,
            coherence_reasoning=evaluation_result.coherence.reasoning if evaluation_result.coherence else "",
            coverage_score=evaluation_result.coverage.score if evaluation_result.coverage else 0,
            coverage_reasoning=evaluation_result.coverage.reasoning if evaluation_result.coverage else "",
            faithfulness_score=evaluation_result.faithfulness.score if evaluation_result.faithfulness else 0,
            faithfulness_reasoning=evaluation_result.faithfulness.reasoning if evaluation_result.faithfulness else "",
            context_relevance_score=evaluation_result.context_relevance.score if evaluation_result.context_relevance else 0,
            context_relevance_reasoning=evaluation_result.context_relevance.reasoning if evaluation_result.context_relevance else "",
            answer_relevance_score=evaluation_result.answer_relevance.score if evaluation_result.answer_relevance else 0,
            answer_relevance_reasoning=evaluation_result.answer_relevance.reasoning if evaluation_result.answer_relevance else "",
            tool_routing_correct=evaluation_result.tool_routing_correct,
            tool_routing_reasoning=evaluation_result.tool_routing_reasoning,
            expected_tool_calls=evaluation_result.expected_tool_calls,
            route_efficiency=evaluation_result.route_efficiency,
            overall_reasoning=evaluation_result.overall_reasoning,
            overall_result=evaluation_result.overall_result,
            created_at=evaluation_result.created_at
        )

        # Add the evaluation result to the session and commit
        self.session.add(evaluation_dao)
        await self.session.commit()
