from typing import Optional
import logging 


class QdrantVersionedMixin():
         
    def retrieve_latest_collection(self, 
                                   collection_name: str) -> Optional[str]:
        collections = self.client.get_collections().collections
        names = [c.name for c in collections]
        if any(name.startswith(collection_name + "_v") for name in names):
            versioned_collections = [name for name in names if name.startswith(collection_name + "_v")]
            latest_version = max(int(name.split("_v")[-1]) for name in versioned_collections)
            latest_collection = f"{collection_name}_v{latest_version}"
            logging.info(f"Latest collection for {collection_name} is {latest_collection}")
            return latest_collection