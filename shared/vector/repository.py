from abc import ABC, abstractmethod


class IVersionedCollectionRepository(ABC):
    """
    An parent interface to be implemented by the vector stores interfaces 
    so they are expected to have versions in their implementations
    """

    @abstractmethod 
    def retrieve_latest_collection(self,
                                   collection_name: str):
        """Retrieve the latest version of the collection with the given name.""" 
        ... 

