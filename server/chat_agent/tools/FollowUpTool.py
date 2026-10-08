from server.chat_agent.schemas import ToolCall
from server.chat_agent.tools.tool import AgentTool
from server.chat_agent.tools.enums import ToolName
import logging

class FollowUpTool(AgentTool):
    def __init__(
            self,
            tools_called: list[ToolCall] = None,
            follow_up_questions: list[dict] = None,  # ← add this
            ):
        super().__init__(ToolName.FOLLOW_UP_QUESTION_GENERATOR, tools_called)
        self.follow_up_questions: list[dict] = follow_up_questions

    async def __call__(
            self,
            generated_questions: list[dict],
            ) -> str:
        
        if not generated_questions:
            return "No follow-up questions generated." 
        
        # append them to the internal list 
        self.follow_up_questions.extend(generated_questions)
        logging.info(f"FollowUpTool: Appended {len(generated_questions)} questions. Total now: {len(self.follow_up_questions)}") 

        return f"Follow-up questions generated and stored. Total questions: {len(self.follow_up_questions)}" 





