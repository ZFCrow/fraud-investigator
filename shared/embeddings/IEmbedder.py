from abc import ABC, abstractmethod

from shared.embeddings.schemas import SparseEmbeddings

class IEmbedder(ABC):

    @abstractmethod
    def embed(self,
              texts: list[str],
              is_query: bool = False,
              ) -> tuple[list[list[float]], list[SparseEmbeddings]]:
        """
        Returns (dense_vectors, sparse_vectors) for a batch of texts.
        is_query marks search queries, which some models encode differently from the documents they search.
        """
        ...
