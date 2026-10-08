from shared.database.service import setup
from shared.embeddings.BGEM3Embedder import BGEM3Embedder
from shared.embeddings.EmbeddingService import EmbeddingService

from server.chat_agent import router
from server.prompt.postgres_repository import PostgresPromptRepository
from shared.settings import settings

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import QdrantClient
from contextlib import asynccontextmanager
import redis.asyncio as aioredis
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")

class SGTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=SGT)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat(sep=' ', timespec='milliseconds')

# set up logger
logging.basicConfig(level=logging.INFO)
for _handler in logging.root.handlers:
    _handler.setFormatter(SGTFormatter('%(asctime)s SGT - %(name)s - %(levelname)s - %(message)s'))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("setting up fastapi")
    
    # 1. Run your setup and get the session factory (single shop database)
    AsyncSessionFactory, engine = await setup()
    
    # 2. Store it in app.state so the rest of the app can see it
    app.state.db_factory = AsyncSessionFactory

    # One-time bootstrap: seed a default active prompt for any PROMPTTYPE that
    # doesn't have one yet (empty/fresh DB). Runs exactly once here, before the
    # app accepts any traffic
    async with AsyncSessionFactory() as session:
        await PostgresPromptRepository(session).setup()



    # qdrant client
    qdrant_client = QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            timeout=300
        )
    
    app.state.qdrant = qdrant_client

    app.state.embedding_service = EmbeddingService(
        embedder = BGEM3Embedder()
    )

    # redis client
    app.state.redis = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        password=settings.REDIS_PASSWORD,
        decode_responses=False,
    )

    yield  # Application runs here

    # 3. Shutdown
    await app.state.redis.aclose()
    await engine.dispose()
     
# 2. Initialize the FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="A production-ready FastAPI template layout.",
    lifespan=lifespan
)


# 3. Configure CORS (Cross-Origin Resource Sharing) Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this to specific domains in production
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Include Modular Routers
app.include_router(router.router)

# 5. Core Root Endpoint
@app.get("/", tags=["Root"])
async def root():
    return {
        "status": "healthy",
        "message": f"Welcome to {settings.APP_NAME}",
        "docs_url": "/docs"
    }



#
from chainlit.utils import mount_chainlit
mount_chainlit(app=app, target="/app/server/chat_agent/ui.py", path="/ui")
#
