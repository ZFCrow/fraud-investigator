# QdrantRepository.py

from qdrant_client import QdrantClient, models
from qdrant_client.models import  Filter


from server.vector.repository import IVectorQueryRepository
from shared.vector.qdrant_mixin import QdrantVersionedMixin 

class QdrantRepository(QdrantVersionedMixin,
                       IVectorQueryRepository,
                       ):
    def __init__(self, 
                 client: QdrantClient, 
                 ):
        self.client = client


    def search(
        self,
        dense_vector: list[float],
        sparse_vector,
        collection_name: str ,
        limit: int = 5,
        query_filter: Filter = None
        
    ):
        if not collection_name:
            raise ValueError("Collection name must be provided for search operation.")


        return self.client.query_points(
            collection_name=collection_name,
            query=models.FusionQuery(
                fusion=models.Fusion.RRF
            ),
            prefetch=[
                models.Prefetch(
                    query=dense_vector,
                    using="text-dense",
                    limit=limit
                ),
                models.Prefetch(
                    query=models.SparseVector(
                        indices=sparse_vector.indices,
                        values=sparse_vector.values
                    ),
                    using="text-sparse",
                    limit=limit
                )
            ],
            query_filter=query_filter,
            limit=limit
        )

    #! retrieve_latest_collection is now implemented in QdrantVersionedMixin, so we don't need to implement it here. 

