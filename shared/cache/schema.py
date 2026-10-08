from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any



class VectorStoreQueryCache(BaseModel): 

    output : list[str]
    input_embeddings : list[float]
