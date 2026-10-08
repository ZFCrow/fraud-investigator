from abc import abstractmethod
from typing import Optional

from ingestor.vector.schemas import Point 
from shared.vector.repository import IVersionedCollectionRepository


from qdrant_client import QdrantClient, models
from qdrant_client.models import PointStruct, VectorParams, SparseVectorParams, Distance, Filter, FieldCondition, Range, DatetimeRange

import logging
from typing import Optional

from shared.vector.qdrant_mixin import QdrantVersionedMixin 


class IVectorIngestionRepository(IVersionedCollectionRepository):

    @abstractmethod
    def snapshot(self, version: Optional[int] = None  ):
        """Create a snapshot of the current state of the vector repository for the given version."""
        ... 

    @abstractmethod 
    def clone (self, 
               source_name: Optional[str] = None, 
               target_name: Optional[str] = None
               ):
        """Clone the state of the vector repository from source_name to target_name ."""
        ... 

    @abstractmethod 
    def setup_collection(self):
        """Setup the vector repository (e.g., create collections, indexes, etc.)."""
        ... 

    @abstractmethod 
    def setup_indexes(self):
        """Setup the necessary indexes in the vector repository."""
        ... 

    @abstractmethod 
    def upsert(self, 
               records: list[Point]):
        """Upsert the given 
        log records into the vector repository.
        """
        ... 

    @abstractmethod
    def get_total_points(self) -> int:
        """Get the total number of points in the vector repository."""
        ... 

# QdrantRepository.py

class QdrantRepository(QdrantVersionedMixin,
                       IVectorIngestionRepository):
    def __init__(self, 
                 client: QdrantClient, 
                 collection_name: Optional[str] = None
                 ):
        
        #! only ingestion pipeline uses self.collection_name
        #! for query , the search must be provided with a collection name 
        #! so it shld be ok for quey pipeline to not pass in a collection_name during init
        self.client = client
        self.collection_name = collection_name

        self.setup_collection() 
        #!self.setup_indexes()

    def snapshot(self, version: Optional[int]): 
        #! for now we will just log the version update, 
        # but in a real implementation we might want to store this in a more robust way 
    
        if version:
            logging.info(f"Updating Qdrant collection version to {version}") 
            # with a version updated, 
            # we can trigger a cloning process to act as a snapshot of the working db    
            self.clone(
                target_name=f"{self.collection_name}_v{version}"
            )
        else:
            logging.info("No version provided for snapshot, skipping cloning process") 

    def clone(self, 
        target_name: str,
        source_name: Optional[str] = None, 
        ): 
        """
        Copy a Qdrant collection into another collection using a point-in-time snapshot.

        By default, the repository's configured collection is used as the source.
        For a versioned ingestion checkpoint, clone `shop_sessions` into a target such
        as `shop_sessions_v3`.

        The method can also restore a versioned collection into the working
        collection—for example, clone `shop_sessions_v3` back into `shop_sessions`.

        Args:
            target_name: Destination collection name. This must be provided.
            source_name: Source collection name. Defaults to the configured working
                collection.
        """

        if self.collection_name is None: 
            raise ValueError("Collection name must be provided for cloning operation.")

        if source_name is None: 
            source_name = self.collection_name 
            
        try: 
            # 1. Fetch current collections to validate names
            collections = [c.name for c in self.client.get_collections().collections]
        
            if source_name not in collections:
                raise ValueError(f"Source collection '{source_name}' not found. Cannot clone.")
                
            if target_name in collections:
                raise ValueError(f"Target destination '{target_name}' already exists. Will not be cloning to avoid overwriting existing data.")
            
            logging.info(f"💾 Initiating stable clone from '{source_name}' -> '{target_name}'...")
            
            # 2. Capture the current state of the vector store
            logging.info(f"Creating point-in-time snapshot for '{source_name}'...")
            snapshot_info = self.client.create_snapshot(collection_name=source_name)
            snapshot_name = snapshot_info.name

            # 3. Restore that exact state into your new stable collection
            logging.info(f"Restoring snapshot state into '{target_name}'...")
            self.client.recover_snapshot(
                collection_name=target_name,
                location=f"file:///qdrant/snapshots/{source_name}/{snapshot_name}",
                priority=models.SnapshotPriority.REPLICA  # Ensures proper data replication mapping
            )

            # 4. Clean up the snapshot archive file from server disk storage
            logging.info(f"Cleaning up temporary snapshot file: {snapshot_name}")
            self.client.delete_snapshot(collection_name=source_name, snapshot_name=snapshot_name)

            logging.info(f"✨ Stable clone successfully created! '{target_name}' is ready to use.")

        except Exception as e:
            logging.error(f"❌ Failed to create stable clone: {str(e)}")
            logging.warning("⚠️  Failed to create stable clone. Proceeding with existing collection.")
        
        
    def setup_collection(self):
        if not self.collection_name: 
            raise ValueError("Collection name must be provided for setup operation.") 

        
        collections = self.client.get_collections().collections
        names = [c.name for c in collections]
        logging.info(f"Setting up collection. Existing collections: {names}") 
        
        if self.collection_name in names:
            logging.info(f"Collection {self.collection_name} already exists, using existing collection")
            return

        #! we either clone a existing versioned collection to the main, 
        #! or we create a new collection if there is no existing collection at all
        source_collection = self.retrieve_latest_collection(self.collection_name)
        if source_collection:
            self.clone(source_name=source_collection, target_name=self.collection_name)
            logging.info(f"Cloned from {source_collection} to {self.collection_name} as the new working collection")
        else:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "text-dense":VectorParams(size=1024, distance=Distance.COSINE)
                    },
                sparse_vectors_config={
                    "text-sparse":SparseVectorParams()
                    }

            )
            logging.info(f"Created collection: {self.collection_name}")

    def setup_indexes(self):
        """
        add as we see fit
        """
        if not self.collection_name: 
            raise ValueError("Collection name must be provided for index setup operation.") 
        indexes = {
            "customer_email": models.PayloadSchemaType.KEYWORD,
            "device_id": models.PayloadSchemaType.KEYWORD,
            "ip_country": models.PayloadSchemaType.KEYWORD,
            "session_start": models.PayloadSchemaType.DATETIME,
            "event_count": models.PayloadSchemaType.INTEGER,
            "declined_payment_count": models.PayloadSchemaType.INTEGER,
        }
        for field_name, field_schema in indexes.items():
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name=field_name,
                field_schema=field_schema,
            )

    def upsert(self, 
               records: list[Point]):
        """Upsert the given 
        log records into the vector repository.
        """
        ... 

    @abstractmethod
    def get_total_points(self) -> int:
        """Get the total number of points in the vector repository."""
        ... 

# QdrantRepository.py

class QdrantRepository(QdrantVersionedMixin,
                       IVectorIngestionRepository):
    def __init__(self, 
                 client: QdrantClient, 
                 collection_name: Optional[str] = None
                 ):
        
        #! only ingestion pipeline uses self.collection_name
        #! for query , the search must be provided with a collection name 
        #! so it shld be ok for quey pipeline to not pass in a collection_name during init
        self.client = client
        self.collection_name = collection_name

        self.setup_collection() 
        #!self.setup_indexes()

    def snapshot(self, version: Optional[int]): 
        #! for now we will just log the version update, 
        # but in a real implementation we might want to store this in a more robust way 
    
        if version:
            logging.info(f"Updating Qdrant collection version to {version}") 
            # with a version updated, 
            # we can trigger a cloning process to act as a snapshot of the working db    
            self.clone(
                target_name=f"{self.collection_name}_v{version}"
            )
        else:
            logging.info("No version provided for snapshot, skipping cloning process") 

    def clone(self, 
        target_name: str,
        source_name: Optional[str] = None, 
        ): 
        """
        Copy a Qdrant collection into another collection using a point-in-time snapshot.

        By default, the repository's configured collection is used as the source.
        For a versioned ingestion checkpoint, clone `shop_sessions` into a target such
        as `shop_sessions_v3`.

        The method can also restore a versioned collection into the working
        collection—for example, clone `shop_sessions_v3` back into `shop_sessions`.

        Args:
            target_name: Destination collection name. This must be provided.
            source_name: Source collection name. Defaults to the configured working
                collection.
        """

        if self.collection_name is None: 
            raise ValueError("Collection name must be provided for cloning operation.")

        if source_name is None: 
            source_name = self.collection_name 
            
        try: 
            # 1. Fetch current collections to validate names
            collections = [c.name for c in self.client.get_collections().collections]
        
            if source_name not in collections:
                raise ValueError(f"Source collection '{source_name}' not found. Cannot clone.")
                
            if target_name in collections:
                raise ValueError(f"Target destination '{target_name}' already exists. Will not be cloning to avoid overwriting existing data.")
            
            logging.info(f"💾 Initiating stable clone from '{source_name}' -> '{target_name}'...")
            
            # 2. Capture the current state of the vector store
            logging.info(f"Creating point-in-time snapshot for '{source_name}'...")
            snapshot_info = self.client.create_snapshot(collection_name=source_name)
            snapshot_name = snapshot_info.name

            # 3. Restore that exact state into your new stable collection
            logging.info(f"Restoring snapshot state into '{target_name}'...")
            self.client.recover_snapshot(
                collection_name=target_name,
                location=f"file:///qdrant/snapshots/{source_name}/{snapshot_name}",
                priority=models.SnapshotPriority.REPLICA  # Ensures proper data replication mapping
            )

            # 4. Clean up the snapshot archive file from server disk storage
            logging.info(f"Cleaning up temporary snapshot file: {snapshot_name}")
            self.client.delete_snapshot(collection_name=source_name, snapshot_name=snapshot_name)

            logging.info(f"✨ Stable clone successfully created! '{target_name}' is ready to use.")

        except Exception as e:
            logging.error(f"❌ Failed to create stable clone: {str(e)}")
            logging.warning("⚠️  Failed to create stable clone. Proceeding with existing collection.")
        
        
    def setup_collection(self):
        if not self.collection_name: 
            raise ValueError("Collection name must be provided for setup operation.") 

        
        collections = self.client.get_collections().collections
        names = [c.name for c in collections]
        logging.info(f"Setting up collection. Existing collections: {names}") 
        
        if self.collection_name in names:
            logging.info(f"Collection {self.collection_name} already exists, using existing collection")
            return

        #! we either clone a existing versioned collection to the main, 
        #! or we create a new collection if there is no existing collection at all
        source_collection = self.retrieve_latest_collection(self.collection_name)
        if source_collection:
            self.clone(source_name=source_collection, target_name=self.collection_name)
            logging.info(f"Cloned from {source_collection} to {self.collection_name} as the new working collection")
        else:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "text-dense":VectorParams(size=1024, distance=Distance.COSINE)
                    },
                sparse_vectors_config={
                    "text-sparse":SparseVectorParams()
                    }

            )
            logging.info(f"Created collection: {self.collection_name}")

    def setup_indexes(self):
        """
        add as we see fit
        """
        if not self.collection_name: 
            raise ValueError("Collection name must be provided for index setup operation.") 
        self.client.create_payload_index(
            collection_name=self.collection_name,
            field_name="user_name",
            field_schema=models.PayloadSchemaType.KEYWORD,
            )

        self.client.create_payload_index(
            collection_name=self.collection_name,
            field_name="session_start",
            field_schema=models.PayloadSchemaType.DATETIME,
            )

        self.client.create_payload_index(
            collection_name=self.collection_name,
            field_name="event_count",
            field_schema=models.PayloadSchemaType.INTEGER,
            )

        self.client.create_payload_index(
            collection_name=self.collection_name,
            field_name="request_count",
            field_schema=models.PayloadSchemaType.INTEGER,
            )

    def upsert(self, 
               sessions: list[Point]
               ) -> None:
        """
        this is the central api that the ingestion pipeline will use to upsert 
        so the caller needs to pass in a list of Points, 
        so they should have their own implementation of points
        """
        if not self.collection_name:
            raise ValueError("Collection name must be provided for upsert operation.")

        UPSERT_BATCH_SIZE = 100  # smaller chunks, well under 32MB limit


        for i in range(0, len(sessions), UPSERT_BATCH_SIZE):
            batch = sessions[i:i + UPSERT_BATCH_SIZE]
            points = [
                PointStruct(
                    id=session.point_id,
                    vector={
                        "text-dense": session.dense,
                        "text-sparse": session.sparse.to_qdrant() if session.sparse else None
                    },
                    payload=session.to_payload()
                )
                for session in batch
            ]
            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True
            )

    #! retrieve_latest_collection is now implemented in QdrantVersionedMixin, so we don't need to implement it here. 
    
        
    def get_total_points(self) -> int:
        if not self.collection_name:
            raise ValueError("Collection name must be provided for total points retrieval.")
        
        collection_info = self.client.get_collection(collection_name=self.collection_name)
        logging.info(f"Collection {self.collection_name} has {collection_info.points_count} points.")
        return collection_info.points_count

    
if __name__ == "__main__":
    
    # Example usage
    client = QdrantClient(host="localhost", port=6333)
    repo = QdrantRepository(
        client,
        collection_name="shop_sessions") 
    repo.get_total_points()
