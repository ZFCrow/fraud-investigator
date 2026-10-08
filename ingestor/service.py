from ingestor.store.repository import ISessionIngestionRepository
from ingestor.embedding.service import PointsEmbeddingService
from ingestor.vector.repository import IVectorIngestionRepository


from shared.checkpoint.Checkpoint import Checkpoint
from shared.checkpoint.CheckpointService import CheckpointService

from ingestor.schemas import IngestionConfig 


# set the info level for logging 
import logging
logging.basicConfig(level=logging.INFO) 

# ingestion.py
async def ingest(
        repo: ISessionIngestionRepository,
        embeddingService: PointsEmbeddingService,
        vector_repo: IVectorIngestionRepository,
        ingestion_config: IngestionConfig,
        checkpoint_service: CheckpointService
        ):
    """
    ! 1) get the last checkpoint
    ! 2) snapshot the current state (typically this should be a no-op since we should already have a snapshot for the current checkpoint version, but just in case we want to reset to an older checkpoint or something, this will ensure we have a snapshot for that version)
    ! 3) run the ingestion strategy to get the latest timestamp of the ingested logs/sessions
    ! 4) update the checkpoint with the new timestamp and create a new snapshot for the new checkpoint version
    !"""
    
    latest_timestamp = None 
    try:
        checkpoint: Checkpoint = await checkpoint_service.get_checkpoint()
        logging.info(f"Current checkpoint: {checkpoint}")

        vector_repo.snapshot(checkpoint.version)

        latest_timestamp = await ingestion_config.strategy.run(repo, 
                                                               embeddingService, 
                                                               vector_repo, 
                                                               checkpoint, 
                                                               checkpoint_service)

    except Exception as e:
        logging.error(f"Error during ingestion: {str(e)}")
        logging.warning("⚠️  Ingestion failed. Check the error logs for details. Will retry in the next cycle.")

    finally:
        if latest_timestamp:
            if checkpoint.last_processed_at is None or latest_timestamp > checkpoint.last_processed_at:

                await checkpoint_service.update_checkpoint(checkpoint.version, latest_timestamp)

                updated_version = checkpoint.version + 1 if checkpoint.version is not None else 1
                vector_repo.snapshot(updated_version)

                logging.info(f"Updated checkpoint to version {updated_version} and last_processed_at {latest_timestamp}")

            else:
                logging.info("No new logs ingested. Checkpoint remains unchanged.")
        else:
            logging.info("No logs were processed. Latest_timestamp is none. Checkpoint remains unchanged.")
            
        logging.info("Ingestion cycle completed. Waiting for the next cycle...")
        logging.info("=="*20) 