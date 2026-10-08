# pydandic 


from datetime import datetime, timezone
import uuid
from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema
from typing import Optional


class MetricResult(BaseModel): 
    score: float = Field(..., description="The score for the evaluation metric.")
    reasoning : str = Field(..., description="The reasoning behind the score for the evaluation metric.") 



class EvaluationResult(BaseModel):
    # Fields typed SkipJsonSchema[...] are set by code, never by the judge. They stay on the
    # model but are left out of the JSON schema the judge LLM is given -- a judge that sees
    # them tends to fill them in (e.g. a made-up agent_trace_id), which fails validation.
    # keep it optional so i can use this to validate the reponse from LLM 
    # i will probably attach it in agent code after the evaluation is done 
    agent_trace_id : SkipJsonSchema[Optional[uuid.UUID]] = Field(default=None, description="The agent trace being evaluated.")

    # Which judge-prompt version (server/prompt) produced this evaluation. Optional
    # for the same reason agent_trace_id is: this model also validates the raw LLM
    # response before that's known. Set by EvaluationService right before persisting,
    # off the Prompt it already fetched from prompt_repo — needed so calibration can
    # tell apart two evaluate() runs over the same agent_trace_id under different
    # candidate judge prompts (see tests/calibration/readme.md, stage 3).
    evaluator_prompt_id : SkipJsonSchema[Optional[uuid.UUID]] = Field(default=None, description="id of the judge prompt (server.prompt.schemas.Prompt) used to produce this evaluation.")

    helpfulness: Optional[MetricResult] = Field(default=None, description="The helpfulness score and reasoning.")
    coherence: Optional[MetricResult] = Field(default=None, description="The coherence score and reasoning.")
    coverage: Optional[MetricResult] = Field(default=None, description="The coverage score and reasoning.")
    faithfulness: Optional[MetricResult] = Field(default=None, description="The faithfulness score and reasoning.")
    context_relevance: Optional[MetricResult] = Field(default=None, description="The context relevance score and reasoning.")
    answer_relevance: Optional[MetricResult] = Field(default=None, description="The answer relevance score and reasoning.")

    # tool routing:
    # - live traffic: populated by the LLM judge's own inference (no ground truth available)
    # - benchmark runs: overwritten deterministically by EvaluationService against expected_tools
    # Deterministic beats the judge's guess whenever ground truth is available. Provenance
    # (which of the two produced this value) isn't tracked as a column — benchmark and live
    # runs are expected to write to separate DBs, so the DB itself is the provenance signal.
    tool_routing_correct: Optional[bool] = Field(default=None, description="Whether the agent called the correct tool(s) for this query.")
    tool_routing_reasoning: Optional[str] = Field(default=None, description="Why tool routing was judged correct/incorrect. LLM-authored on live traffic; left as-is on a deterministic benchmark override.")

    # route efficiency = actual tool calls / expected tool calls, computed in EvaluationService
    # (never by the LLM — same reasoning as overall_result: arithmetic is code's job, not the judge's).
    # expected_tool_calls is ground truth from the golden dataset on benchmark runs, or the judge's
    # own estimate of "how many calls should this query reasonably need" on live traffic.
    # Ratio > 1 unambiguously means wasted calls. Ratio < 1 is ambiguous on its own — a genuine
    # shortcut and a skipped necessary step both produce it — read alongside faithfulness/coverage.
    expected_tool_calls: Optional[int] = Field(default=None, description="Ground truth (benchmark) or LLM-estimated (live) number of tool calls this query should reasonably need.")
    route_efficiency: SkipJsonSchema[Optional[float]] = Field(default=None, description="actual_tool_calls / expected_tool_calls, computed deterministically in EvaluationService.")

    overall_reasoning : str = Field(..., description="The overall reasoning for the evaluation.")
    overall_result : float = Field(default=0.0, description="The overall evaluation result score.")


    created_at: SkipJsonSchema[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))

    # specifically for validations - NOT MAPPED to the database, just for the purpose of validation
    reflected: SkipJsonSchema[Optional[bool]] = Field(default=False, description="Whether the evaluation was reflected upon (for validation).")

class TestEvaluationResult(EvaluationResult):
    # benchmark-only — answer_correct requires a reference answer to compare against,
    # which only ever exists on benchmark runs. Kept off the base EvaluationResult (and
    # off the live `evaluation` SQL table entirely) rather than a column that's null on
    # ~90% of rows; TestEvaluator/FileEvaluationRepository are the only things that
    # populate or persist this. Not folded into overall_result — that stays a pure
    # response-quality read so it's comparable between live and benchmark rows.
    answer_correct: Optional[bool] = Field(default=None, description="Whether the answer is correct or not.")
    answer_correctness_reasoning: Optional[str] = Field(default=None, description="Reasoning for the answer correctness assessment.")


 