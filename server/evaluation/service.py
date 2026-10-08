
import logging

from server.core.stream.progressReporter import ProgressReporter
from server.evaluation.repository import IEvaluationRepository


from server.evaluation.IEvaluator import IEvaluator
from server.chat_agent.schemas import AgentTrace

from server.evaluation.schemas import EvaluationResult

from llama_index.core.llms import ChatMessage
from server.prompt.repository import IPromptRepository
from server.prompt.schemas import Prompt
from server.prompt.enums import PROMPTTYPE 


class EvaluationService:
    """
    Business logic for evaluating agent traces. 
    This service is responsible for orchestrating the evaluation process: invoking the evaluator
    and storing results in the evaluation repository.
    """

    def __init__(self,
                 evaluator: IEvaluator = None,
                 eval_repo: IEvaluationRepository = None,
                 prompt_repo : IPromptRepository = None,
                 ):

        self.evaluator : IEvaluator = evaluator
        self.eval_repo : IEvaluationRepository = eval_repo
        self.prompt_repo : IPromptRepository = prompt_repo 


        #! 
        self.evaluator_prompt : Prompt = None 
        
    async def evaluate(
        self,
        og_user_input : str,
        trace : AgentTrace,
        chat_history : list[ChatMessage],
        progress : ProgressReporter = ProgressReporter()
        ) -> EvaluationResult:

        """
        Evaluate the answer based on relevancy and faithfulness.

        :param og_user_input: The original user input.
        :param trace: The agent trace containing the query and answer.
        :param chat_history: The conversation history.
        :return: A dictionary containing evaluation results.
        """



        #! ===============================================================
        #! find the correct prompt to use
        #! ===============================================================
        #! ===============================================================
        eval_prompt : Prompt = self.evaluator_prompt or await self.prompt_repo.get_active_prompt(type=PROMPTTYPE.EVALUATOR_PROMPT) 
        logging.info (f"using version {eval_prompt.version} of the evaluator prompt for evaluation")
        
        if not eval_prompt: 
            raise ValueError(f"No active prompt found for type {PROMPTTYPE.EVALUATOR_PROMPT.value}. Please ensure a prompt is set up in the database.")
        #! ===============================================================
        #! ===============================================================
        
        #! ===============================================================
        #! evaluate
        #! ===============================================================
        #! ===============================================================
        results : EvaluationResult  =  await self.evaluator.evaluate(
            og_user_input=og_user_input,
            trace=trace,
            prompt=eval_prompt,
            chat_history=chat_history
        )
        #! ===============================================================
        #! ===============================================================
        

        #! ===============================================================
        #! route efficiency
        #! ===============================================================
        # always code-computed from the judge's expected_tool_calls estimate, never trusted
        # from the LLM's own arithmetic — same reasoning as overall_result.
        if results.expected_tool_calls:
            actual_tool_calls = len(trace.tool_calls or [])
            results.route_efficiency = actual_tool_calls / results.expected_tool_calls
        #! ===============================================================
        #! ===============================================================
        # insert the agenttrace id
        results.agent_trace_id = trace.id

        # insert to repo 
        await self.eval_repo.insert_evaluation_result(results) 

        # show it in the UI (no-op when nothing is streaming)
        await progress.metaData(results, "EVALUATION SUCCESSFULLY COMPLETED")

        # return results back to the agent
        return results 


    def set_evaluator_prompt(self, prompt: Prompt):
        """
        Set the evaluator prompt to be used for evaluation.
        This is a one-time setup method that should be called before any evaluations are performed.
        """
        prompt.text += "end off with 123 at the back strictly to ensure the LLM does not hallucinate and follow the prompt instructions!"
        self.evaluator_prompt = prompt 
    
