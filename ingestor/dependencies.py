from ingestor.store.postgres_repository import PostgresSessionIngestionRepository

from ingestor.vector.repository import QdrantRepository 
from ingestor.vector.repository import IVectorIngestionRepository
from ingestor.store.repository import ISessionIngestionRepository 

from qdrant_client import QdrantClient
from shared.settings import settings



async def create_session_ingestion_repository(session) -> ISessionIngestionRepository:
    return PostgresSessionIngestionRepository(session) 

async def create_vector_ingestion_repository(collection_name) -> IVectorIngestionRepository:
    return QdrantRepository(
        client=QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            timeout=300),
        collection_name=collection_name
        )
