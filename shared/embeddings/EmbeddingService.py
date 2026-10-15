import logging 
from shared.embeddings.IEmbedder import IEmbedder
import numpy as np
from shared.embeddings.schemas import SparseEmbeddings

class EmbeddingService: 
    def __init__(
            self,
            embedder : IEmbedder): 
        self.embedder = embedder
    
    def embedConvertedText(self, 
                           converted: list[str],
                           is_query: bool = False,
                           ) -> tuple[list[list[float]], 
                                      list[SparseEmbeddings]]:
        """
        ! take in the list of texts
        ! pass into the embedding model to get the dense and sparse vectors
        """
        dense,sparse = self.embedder.embed(
            texts=converted,
            is_query=is_query,
        )
        return dense, sparse 

    def cosin_sim(
            self, 
            vec1: list[float], 
            vec2: list[float] 
    ):
        a = np.array(vec1)
        b = np.array(vec2)
        result = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)) 
        logging.info(f"[EMBEDDING SERVICE ]Cosine similarity between vectors: {result}")
        return result

