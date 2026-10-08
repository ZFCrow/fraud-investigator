
from ingestor.store.repository import ISessionIngestionRepository
from ingestor.schemas import IngestionConfig, SESSIONS


from shared.database.service import setup

# Embeddings 
from shared.embeddings.BGEM3Embedder import BGEM3Embedder
from ingestor.embedding.service import PointsEmbeddingService

# Ingestion Service 
from ingestor.service import ingest

# IVector Repositories 
from ingestor.vector.repository import IVectorIngestionRepository


# checkpoints 
from shared.checkpoint.CheckpointService import CheckpointService
from shared.checkpoint.CheckpointRepository import CheckpointRepository

import asyncio 

from ingestor.dependencies import (
    create_session_ingestion_repository,
    create_vector_ingestion_repository
)
async def main():
    #0 Define the strategy config
    strategy_config : IngestionConfig = SESSIONS

    # 1. Await the setup to get your factory
    # Note: tables must already exist (alembic upgrade head)
    AsyncSessionFactory, engine = await setup()

    # 1.1 creating an instance of embeddingService 
    embeddingService = PointsEmbeddingService(
        embedder = BGEM3Embedder()
    ) 

    # 2. Use the factory to create a session
    # We use 'async with' to ensure the session closes properly
    async with AsyncSessionFactory() as session:

        repo : ISessionIngestionRepository = await create_session_ingestion_repository(session)
        vector_repo : IVectorIngestionRepository = await create_vector_ingestion_repository(strategy_config.vector_collection_name.value)
        
        
        # checkpoint service 
        checkpoint_repo = CheckpointRepository(
            checkpoint_file  =  strategy_config.checkpoint_file,
            offset_file = strategy_config.offset_file
        )

        checkpoint_service = CheckpointService(checkpoint_repo)

        
        # ingestion ! 
        await ingest(repo, 
                     embeddingService, 
                     vector_repo,
            ingestion_config = strategy_config,
            checkpoint_service=checkpoint_service
        )

if __name__ == "__main__":
    # This is the "battery" that starts the async loop
    asyncio.run(main())
    