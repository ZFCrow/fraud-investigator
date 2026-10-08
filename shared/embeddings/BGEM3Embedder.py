
from shared.embeddings.IEmbedder import IEmbedder
from shared.embeddings.schemas import SparseEmbeddings
from FlagEmbedding import BGEM3FlagModel



class BGEM3Embedder(IEmbedder):
    def __init__(self, 
                 model_name: str = 'BAAI/bge-m3', 
                 cache_dir: str = '/app/shared/model_cache'):

        self._model = BGEM3FlagModel(
            model_name, 
            use_fp16=True, 
            cache_dir=cache_dir)

    def embed(self, 
              texts: list[str]
              ) -> tuple[list[list[float]], list[SparseEmbeddings]]:

        #* returns a dict with keys: dense_vecs, lexical_weights, colbert_vecs 
        output = self._model.encode(
            # bge-m3's native limit; session texts reach ~6k tokens and anything
            # past max_length is silently dropped from both dense and sparse vectors
            texts, batch_size=15, max_length=8192,
            return_dense=True, return_sparse=True, return_colbert_vecs=False,
        )

        #* converts the sparse vectors into a format aligned with the SparseEmbeddings dataclass 
        sparse_raw : list[dict[str, float]] = output['lexical_weights']
        sparse : list[SparseEmbeddings] = [self.convert_sparse_vector(s) for s in sparse_raw]

        dense : list[list[float]] = output['dense_vecs'].tolist() 
        return dense, sparse 


    def convert_sparse_vector(self,sparse_dict) -> SparseEmbeddings:
        """
        Convert a sparse vector represented as a dictionary to the SparseEmbeddings format.
        e.g.
        input: { "3": 0.5, "10": 0.8 }
        output: SparseEmbeddings(indices=[3, 10], values=[0.5, 0.8]) 
        """
        return SparseEmbeddings(
            indices=[int(k) for k in sparse_dict.keys()],
            values=list(sparse_dict.values())
        )