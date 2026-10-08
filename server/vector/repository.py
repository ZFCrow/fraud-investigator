from abc import abstractmethod

from shared.vector.repository import IVersionedCollectionRepository
class IVectorQueryRepository(IVersionedCollectionRepository):

    @abstractmethod 
    def search(self):
        """Search for points in the vector repository based on a query."""
        ... 

