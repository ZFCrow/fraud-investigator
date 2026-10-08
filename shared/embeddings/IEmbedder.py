from abc import ABC, abstractmethod

from shared.embeddings.schemas import SparseEmbeddings

class IEmbedder(ABC):

    @abstractmethod
    def embed(self, 
              texts: list[str]
              ) -> tuple[list[list[float]], list[SparseEmbeddings]]:
        """Returns (dense_vectors, sparse_vectors_as_index_weight_dicts) for a batch of texts."""
        ...