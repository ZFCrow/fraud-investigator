from datetime import datetime, timezone 
import logging

from typing import Optional 


from llama_index.core.llms import LLM, ChatMessage

from server.evaluation.IEvaluator import IEvaluator
from server.chat_agent.schemas import AgentTrace
from server.prompt.schemas import Prompt

from server.evaluation.schemas import EvaluationResult, TestEvaluationResult


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
        expected_answer: Optional[str] = None,
    ) -> EvaluationResult:

        history_str = "\n".join(
            f"{m.role}: {m.content}" for m in chat_history
        ) or "None"

        contexts_str = "\n\n".join(
            f"[{tc.tool_name}]: {tc.model_dump(mode='json')['output']}"
            for tc in trace.tool_calls
        ) if trace.tool_calls else "None"

        if expected_answer:
            group4 = f"""
GROUP 4 - Answer Correctness (benchmark only):
Reference (ground-truth) answer: "{expected_answer}"
Compare the agent response above against this reference.
- answer_correct: true/false — does the agent response convey the same facts as the reference
  answer (same entities, numbers, conclusions)? Judge substance, not exact wording.
  A reference answer IS provided above, so answer_correct is REQUIRED to be true or false —
  null is not a valid value here, even when the reference describes a ranked/multi-candidate
  or narrative pattern (e.g. "closest match is X, other candidates Y, Z") or is otherwise hard
  to compare precisely. In that case judge whether the agent's response is substantively
  consistent with the reference's core claim, and pick the closer of true/false — do not abstain.
  null is reserved exclusively for when no reference answer was provided at all (not this case).
- answer_correctness_reasoning: One sentence on why. Also required, non-null, whenever
  answer_correct is true/false.
CORRECTION: You left answer_correct null last time even though a reference answer was provided above. 
That is not allowed. You must commit to true or false now, judging substantive consistency with the 
reference even if it describes a fuzzy or multi-candidate pattern."
"""


        # 1. Choose the correct output class
        output_cls = TestEvaluationResult if expected_answer else EvaluationResult
        
        # 2. Wrap your string in a PromptTemplate (remove the {json_schema} part from your EVALUATOR_PROMPT string)
        prompt_tmpl = PromptTemplate(prompt.text)

        try:
            # 3. Call astructured_predict.
            #! Pass variables directly as keyword arguments. LlamaIndex formats them automatically.
            response : EvaluationResult | TestEvaluationResult = await self.llm.astructured_predict(
                output_cls, # this will be the class that will auto parse 
                prompt_tmpl,
                history=history_str,
                query=og_user_input,
                response=trace.output or "",
                contexts=contexts_str,
                group4=group4 if expected_answer else ""
            )

            # Belt-and-suspenders: the prompt forbids null answer_correct whenever a
            # reference answer was given, but structured-output judges don't always
            # comply with prose instructions on fuzzy/narrative references. Retry once
            # with an explicit correction rather than silently persisting a null that
            # should have been true/false.
            if expected_answer and getattr(response, "answer_correct", None) is None:
                logging.warning(
                    "Evaluator returned null answer_correct despite a reference answer "
                    "being provided — retrying once with a corrective instruction."
                )
                response = await self.llm.astructured_predict(
                    output_cls,
                    prompt_tmpl,
                    history=history_str,
                    query=og_user_input,
                    response=trace.output or "",
                    contexts=contexts_str,
                    group4=group4
                )
                if getattr(response, "answer_correct", None) is None:
                    logging.warning(
                        "Evaluator still returned null answer_correct after retry; "
                        "persisting null."
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
