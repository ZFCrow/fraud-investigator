
import numpy as np
from fastembed import SparseTextEmbedding
from openai import OpenAI

from shared.embeddings.IEmbedder import IEmbedder
from shared.embeddings.schemas import SparseEmbeddings
from shared.settings import settings


# Qwen3-Embedding is instruction-aware on the query side only; documents are embedded as-is
QUERY_INSTRUCTION = ("Instruct: Given a question about storefront customer sessions, "
                     "retrieve the session summaries that answer it\nQuery: ")


class NebiusEmbedder(IEmbedder):
    """
    Dense vectors from a Nebius Token Factory embedding model, sparse vectors from local BM25.

    Token Factory's /v1/embeddings only returns dense vectors, so the sparse half of hybrid
    retrieval is BM25 (fastembed's Qdrant/bm25: a tokenizer + stemmer, no model weights).
    BM25 vectors carry term frequency only — the collection's text-sparse vector must be
    created with Modifier.IDF so Qdrant applies the corpus-wide IDF at query time.
    """
    def __init__(self,
                 model_name: str = settings.EMBEDDING_MODEL,
                 dim: int = settings.EMBEDDING_DIM,
                 batch_size: int = 16,
                 cache_dir: str = '/app/shared/model_cache'):

        if not settings.NEBIUS_API_KEY or not model_name:
            raise RuntimeError("NEBIUS_API_KEY and EMBEDDING_MODEL must be set to embed with Nebius")

        self._client = OpenAI(base_url=settings.NEBIUS_BASE_URL, api_key=settings.NEBIUS_API_KEY)
        self._model_name = model_name
        self._dim = dim
        self._batch_size = batch_size
        self._bm25 = SparseTextEmbedding("Qdrant/bm25", cache_dir=cache_dir)

    def embed(self,
              texts: list[str],
              is_query: bool = False,
              ) -> tuple[list[list[float]], list[SparseEmbeddings]]:

        dense_input : list[str] = [QUERY_INSTRUCTION + t for t in texts] if is_query else texts
        dense : list[list[float]] = []
        for start in range(0, len(dense_input), self._batch_size):
            dense.extend(self.embed_dense(dense_input[start:start + self._batch_size]))

        # BM25 query vectors weight each distinct term once; document vectors carry term frequency
        sparse_raw = self._bm25.query_embed(texts) if is_query else self._bm25.embed(texts)
        sparse : list[SparseEmbeddings] = [
            SparseEmbeddings(indices=s.indices.tolist(), values=s.values.tolist()) for s in sparse_raw
        ]
        return dense, sparse

    def embed_dense(self, batch: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(
            model=self._model_name, input=batch, dimensions=self._dim
        )
        # the API may return items out of order; .index is the position in the request
        vectors = [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
        return [self.truncate(v) for v in vectors]

    def truncate(self, vector: list[float]) -> list[float]:
        """
        Matryoshka fallback: if the endpoint ignored `dimensions`, keep the leading dims and
        re-normalise, which is how Qwen3-Embedding's smaller sizes are defined.
        """
        if len(vector) <= self._dim:
            return vector
        head = np.array(vector[:self._dim])
        return (head / np.linalg.norm(head)).tolist()
