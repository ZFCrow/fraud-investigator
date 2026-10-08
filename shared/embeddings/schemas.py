

from qdrant_client.models import SparseVector

#! pydandic 
from pydantic import BaseModel 


#! owns everything about how to store it in Qdrant. 
class SparseEmbeddings(BaseModel):
    indices: list[int]
    values: list[float]

    def to_qdrant(self) -> SparseVector:
        return SparseVector(indices=self.indices, values=self.values)




