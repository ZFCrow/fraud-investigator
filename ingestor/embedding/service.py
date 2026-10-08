import logging 
from shared.embeddings import IEmbedder
from shared.embeddings.EmbeddingService import EmbeddingService
from ingestor.vector.schemas import Point

class PointsEmbeddingService(EmbeddingService): 
    def __init__(
            self,
            embedder : IEmbedder): 
        super().__init__(embedder)  # delegates to parent, sets self.embedder


    def embed_points(self, session_points: list[Point]) -> list[Point]:
        """
        #! now that it is points , the next time new strategies just need to make sure to convertthem to points before passing thme in here !
        #! they can be session_points or log_points or any other point type that implements the Point interface 
        """

        logging.info(f"Embedding {len(session_points)} points") 
        logging.info(f" Converting to text format")

        converted : list[str] = [session.to_text() for session in session_points]

        # call the embedding model here and return the vectors 
        dense, sparse = self.embedConvertedText(converted)


        # Attach the dense and sparse vectors to the SessionPoint objects
        for session_point, dense_vec, sparse_vec in zip(session_points, dense, sparse):
            session_point.dense = dense_vec
            session_point.sparse = sparse_vec

        logging.info(f"Embedded {len(session_points)} points with dense and sparse vectors")

        return session_points
    