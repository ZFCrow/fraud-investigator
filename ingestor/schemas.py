from dataclasses import dataclass

from ingestor.strategy import IngestionStrategy, SessionIngestionStrategy
from shared.vector.enums import VectorStoreCollectionNames

from pathlib import Path

from shared.settings import settings


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CHECKPOINT_DIR = Path(settings.CHECKPOINT_DIR) if settings.CHECKPOINT_DIR else _REPO_ROOT / "shared" / "checkpoint"

@dataclass(frozen=True)
class IngestionConfig:
    strategy: IngestionStrategy
    vector_collection_name: VectorStoreCollectionNames
    checkpoint_file : Path
    offset_file : Path


SESSIONS = IngestionConfig(
    strategy=SessionIngestionStrategy(),
    vector_collection_name=VectorStoreCollectionNames.SESSIONS,
    checkpoint_file=_CHECKPOINT_DIR / "shop_sessions_checkpoint.txt",
    offset_file=_CHECKPOINT_DIR / "shop_sessions_offset.txt"
)

TEST_SESSIONS = IngestionConfig(
    strategy=SessionIngestionStrategy(),
    vector_collection_name=VectorStoreCollectionNames.TEST_SESSIONS,
    checkpoint_file=_CHECKPOINT_DIR / "test_shop_sessions_checkpoint.txt",
    offset_file=_CHECKPOINT_DIR / "test_shop_sessions_offset.txt"
)
