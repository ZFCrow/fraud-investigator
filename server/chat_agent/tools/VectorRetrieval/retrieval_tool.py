from abc import abstractmethod

from server.chat_agent.schemas import ToolCall
from server.chat_agent.tools.tool import AgentTool
from server.chat_agent.tools.enums import ToolName
from shared.embeddings.EmbeddingService import EmbeddingService


from server.vector.repository import IVectorQueryRepository
from shared.cache.ICacheRepository import ICacheRepository
from shared.cache.schema import VectorStoreQueryCache
from shared.vector.enums import VectorStoreCollectionNames

from qdrant_client.models import QueryResponse, DatetimeRange, Range, FieldCondition, MatchValue, Filter
from datetime import datetime
import logging


class VectorRetrievalTool(AgentTool):
    @abstractmethod
    async def __call__(
                self, 
                query: str, 
                limit: int = 10,
                **kwargs # any form of filters 
                ) -> list[str]:
        pass

class SessionRetrievalTool(VectorRetrievalTool): 
    def __init__(self, 
                repo : IVectorQueryRepository, 
                embedding_service : EmbeddingService,
                cache_repo : ICacheRepository,

                # list of tools_called
                tools_called: list[ToolCall] = None,
                 ):
        super().__init__(ToolName.QUERY_SESSION_VECTOR_HYBRID, tools_called)
        self.repo = repo
        self.embedding_service = embedding_service
        self.cache_repo = cache_repo

    async def __call__(self,
                query: str, 
                limit: int = 10,
                filter_customer_email: str = None,
                filter_device_id: str = None,
                filter_ip_country: str = None,
                filter_start_date: str = None,  # ISO format string 
                filter_end_date: str = None,    # ISO format string 
                filter_event_count: int = None,
                filter_declined_payments: int = None,
                ) -> list[str]:

        # embed internally, agent just passes the query string
        dense, sparse = self.embedding_service.embedConvertedText([query], is_query=True)
        dense = dense[0]
        sparse = sparse[0] 
        
        cache_key = (f"query:{filter_customer_email}:{filter_device_id}:{filter_ip_country}:{filter_start_date}:"
                     f"{filter_end_date}:{filter_event_count}:{filter_declined_payments}")

        #*====================================================================================================
        #*====================================================================================================
        #* PULL FROM REDIS
        #* for each cached, find cosin sim between the dense and the embedding in the cache
        #*====================================================================================================
        #*====================================================================================================`
        query_list_bytes : list[bytes] = await self.cache_repo.get_list(cache_key)

        query_list : list[VectorStoreQueryCache] = [VectorStoreQueryCache.model_validate_json(b) for b in query_list_bytes]
        # for each one, use the embeddings find the most similar and see if its above threshold
        if len (query_list) > 0: 
            logging.info(f"[CACHE HIT]: Found {len(query_list)} cached queries for the given filters with redis key {cache_key}. Checking for similarity...")


        for query in query_list:
            sim = self.embedding_service.cosin_sim(dense, query.input_embeddings) 
            if sim > 0.9: 
                logging.info(f"[CACHE HIT]: Found similar query in cache with similarity {sim}. Returning cached result.")
                return query.output 

        #*====================================================================================================
        #*====================================================================================================
        
        
        logging.info("[CACHE MISS] NO SIMILAR QUERIES FOUND IN CACHE, QUERYING VECTOR STORE")
        # building the filter based on the provided parameters
        conditions = [] 

        for key, value in (("customer_email", filter_customer_email),
                           ("device_id", filter_device_id),
                           ("ip_country", filter_ip_country)):
            if value is not None:
                conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))

        if filter_start_date is not None:
            conditions.append(FieldCondition(
                key="session_start",
                range=DatetimeRange(gte=datetime.fromisoformat(filter_start_date))
            )) 

        if filter_end_date is not None: 
            conditions.append(FieldCondition(
                key="session_start",
                range=DatetimeRange(lte=datetime.fromisoformat(filter_end_date))
            )) 

        if filter_event_count is not None: 
            conditions.append(FieldCondition(
                key="event_count",
                range=Range(gte=filter_event_count)
            )) 

        if filter_declined_payments is not None:
            conditions.append(FieldCondition(
                key="declined_payment_count",
                range=Range(gte=filter_declined_payments)
            ))

        query_filter = Filter(must=conditions) if conditions else None 

        # get the collection to query 
        #! get from cache first
        #! else qdrant repo to compute the latest version for it
        raw_collection_name : bytes = await self.cache_repo.get(VectorStoreCollectionNames.SESSIONS.value)  # cache key is the enum value
        if raw_collection_name: 
            collection_name : str = raw_collection_name.decode('utf-8') 
            logging.info (f"[CACHE HIT]: Retrieved collection name from cache: {collection_name}")

        else:
            collection_name : str = self.repo.retrieve_latest_collection(VectorStoreCollectionNames.SESSIONS.value)  # use the enum value for retrieval 
            if not collection_name: 
                return "No collection found for retrieval."

            # SET THE CACHE for the collection name for future retrievals (dont need if alr foudn it in cache)
            await self.cache_repo.set(VectorStoreCollectionNames.SESSIONS.value, collection_name.encode(), ttl=3600)  # cache for 1 hour
            logging.info (f"Set cache for collection name: {collection_name}")
        
        logging.info (f"Using collection: {collection_name} for retrieval") 
        results : QueryResponse = self.repo.search(dense, 
                                                   sparse, 
                                                   limit=limit, 
                                                   query_filter=query_filter, 
                                                   collection_name=collection_name)
        print ("retrieved type is ", type(results)) 

        
        # format it 
        formatted : list[str] = []

        for p in results.points:
            formatted.append(
            f"[Score: {p.score:.2f}] {p.payload.get('customer_email') or 'guest'} | Session ID: {p.id} | "
            f"Session: {p.payload.get('session_start')} → {p.payload.get('session_end')} | "
            f"device {p.payload.get('device_id')} | IP country {p.payload.get('ip_country')} | "
            f"{p.payload.get('event_count')} events | {p.payload.get('payment_attempt_count')} payment attempts "
            f"({p.payload.get('declined_payment_count')} declined) | {p.payload.get('order_count')} orders\n"
            f"Summary: {p.payload.get('text', '')}"
            ) 

        #!================================
        #! appending to redis cache for future retrievals 
        #!================================
        
        vectorcache = VectorStoreQueryCache(
            output = formatted,
            input_embeddings = dense
        )
        await self.cache_repo.add_to_list(cache_key, vectorcache.model_dump_json().encode("utf-8"), ttl=3600)
        #!================================
        #!================================

        return formatted    

        
