from datetime import datetime

from shared.checkpoint.Checkpoint import Checkpoint, OffsetState
from shared.checkpoint.CheckpointRepository import CheckpointRepository


class CheckpointService:
    def __init__(self, repo: CheckpointRepository):
        self.repo = repo

    async def get_checkpoint(self) -> Checkpoint:
        return await self.repo.get()

    async def update_checkpoint(self, version: int = None, last_processed_at: datetime = None):
        await self.repo.update(version, last_processed_at)

    async def get_offset(self) -> OffsetState:
        return await self.repo.get_offset()

    async def update_offset(self, version: int, offset: int, total_vectors: int = 0):
        await self.repo.update_offset(version, offset, total_vectors)
