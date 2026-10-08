from pydantic import BaseModel
from typing import Literal, Optional, Union

class StreamEvent(BaseModel):
    event: Literal["progress", "answer", "done", "error", "metadata","graph", "action"]

    
    data: Optional[Union[str, dict]] = None