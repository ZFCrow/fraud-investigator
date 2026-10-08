from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class Checkpoint:
    version: Optional[int]
    last_processed_at: Optional[datetime]

@dataclass
class OffsetState:
    version: Optional[int]
    offset: int = 0
    total_vectors: int = 0
