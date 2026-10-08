from abc import ABC, abstractmethod
from datetime import datetime
import logging

from ingestor.store.repository import ISessionIngestionRepository
from ingestor.embedding.service import PointsEmbeddingService
from shared.checkpoint.Checkpoint import Checkpoint, OffsetState
from shared.checkpoint.CheckpointService import CheckpointService


from ingestor.vector.repository import IVectorIngestionRepository
from ingestor.vector.schemas import Point, SessionPoint


class IngestionStrategy(ABC):
    @abstractmethod
    async def run(self,
                  repo: ISessionIngestionRepository,
                  embeddingService: PointsEmbeddingService,
                  vector_repo: IVectorIngestionRepository,
                  checkpoint: Checkpoint,
                  checkpoint_service: CheckpointService
                  ) -> datetime:
        pass

class SessionIngestionStrategy(IngestionStrategy):
    """
    Ingestion strategy for storefront sessions.

    Fetches user activity sessions via an injected repository, splits
    oversized sessions into embeddable chunks, converts them into
    SessionPoint objects, embeds them, and upserts the results into
    the vector store. Progress is checkpointed periodically to allow
    resumable ingestion.
    """

    async def run(self, 
                  repo : ISessionIngestionRepository, 
                  embeddingService : PointsEmbeddingService, 
                  vector_repo : IVectorIngestionRepository, 
                  checkpoint : Checkpoint, 
                  checkpoint_service: CheckpointService):
        
        latest_timestamp = checkpoint.last_processed_at

         # v+1 is the version we're currently working toward
        in_progress_version = (checkpoint.version or 0) + 1

        # resume mid-ingestion if offset.txt recorded progress for this version
        offset_state : OffsetState = await checkpoint_service.get_offset()
        
        if offset_state.version == in_progress_version:
            total_ingested = offset_state.offset
            total_vectors = offset_state.total_vectors 

        else:
            #! if offset version is <= checkpointversion ==> offset was for previous run and completed
            #! if offset version is > in_progress_version ==> not a valid state
            total_ingested = 0
            total_vectors = 0

        if total_ingested:
            logging.info(f"Resuming ingestion at offset {total_ingested} for v{in_progress_version}")

        batch_num = 0 
        async for batch in repo.get_logs_since(checkpoint.last_processed_at, offset=total_ingested):
            batch_num += 1
            logging.info(f"Processing batch of {len(batch)} sessions")

            #! covnert it to session points 
            session_points : list[Point] = [SessionPoint(session=session) for session in batch]

            #! reuse the same embedding service 
            session_points = embeddingService.embed_points(session_points)

            vector_repo.upsert(sessions=session_points)

            # find the latest timestamp
            batch_max = max(session.session_end for session in batch) 
            latest_timestamp = ( 
                max(latest_timestamp, batch_max) if latest_timestamp else batch_max
            ) 

            total_ingested += len(batch)
            total_vectors += len(batch)
            total_vectors_in_store = vector_repo.get_total_points()  # Update the total points in


            if batch_num % 5 == 0:
                await checkpoint_service.update_offset(in_progress_version, total_ingested, total_vectors) 

            logging.info(
                f"Batch processed. "
                f"Sessions/offset: {total_ingested} | "
                f"Vectors upserted (one per session): {total_vectors} | "
                f"Total vectors in Qdrant: {total_vectors_in_store}"
            )
            
        return latest_timestamp