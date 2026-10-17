from datetime import datetime, timezone 
import logging

from typing import Optional 


from llama_index.core.llms import LLM, ChatMessage

from server.evaluation.IEvaluator import IEvaluator
from server.chat_agent.schemas import AgentTrace
from server.prompt.schemas import Prompt

from server.evaluation.schemas import EvaluationResult


from llama_index.core.prompts import PromptTemplate

class LLMEvaluator(IEvaluator):
    def __init__(self, llm: LLM):
        # the judge model is picked in server/core/dependencies.py, not here -- any
        # LLM that supports structured output (astructured_predict) works
        self.llm = llm

    async def evaluate(
        self,
        og_user_input : str, 
        trace: AgentTrace,
        prompt : Prompt,  
        chat_history: list[ChatMessage],
    ) -> EvaluationResult:

        history_str = "\n".join(
            f"{m.role}: {m.content}" for m in chat_history
        ) or "None"

        contexts_str = "\n\n".join(
            f"[{tc.tool_name}]: {tc.model_dump(mode='json')['output']}"
            for tc in trace.tool_calls
        ) if trace.tool_calls else "None"


        # 2. Wrap your string in a PromptTemplate (remove the {json_schema} part from your EVALUATOR_PROMPT string)
        prompt_tmpl = PromptTemplate(prompt.text)

        try:
            # 3. Call astructured_predict.
            #! Pass variables directly as keyword arguments. LlamaIndex formats them automatically.
            response : EvaluationResult = await self.llm.astructured_predict(
                EvaluationResult, # this will be the class that will auto parse 
                prompt_tmpl,
                history=history_str,
                query=og_user_input,
                response=trace.output or "",
                contexts=contexts_str,
            )


            response.created_at = datetime.now(timezone.utc)
            response.reflected = False  # default to False; will be set to True if this evaluation is reflected upon during validation 
            
            # Stamp which judge-prompt version produced this result — `prompt` is
            # the same Prompt EvaluationService fetched from prompt_repo and handed
            # in above; this class already has it in scope, so this is the one
            # place that needs to set it (no need to also set it back in
            # EvaluationService before insert).
            response.evaluator_prompt_id = prompt.id
            logging.info(f"Evaluator response: {response}")
            return response

        except Exception as e:
            logging.error(f"Error during evaluation: {e}")
            raise 
