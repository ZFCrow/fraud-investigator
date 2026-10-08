import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from shared.checkpoint.Checkpoint import Checkpoint, OffsetState


class CheckpointRepository:
    def __init__(self,
                 checkpoint_file: Optional[Path]  = None,
                 offset_file: Optional[Path] = None):
        self.tz = timezone(timedelta(hours=8))
        self.checkpoint_file = checkpoint_file
        self.offset_file = offset_file

        if not self.checkpoint_file or not self.offset_file:
            raise ValueError("Checkpoint file and offset file paths must be provided.") 

        if not self.checkpoint_file.exists() or self.checkpoint_file.stat().st_size == 0:
            self.checkpoint_file.write_text("date,version,last_processed_at\n")
        else:
            self.checkpoint_file.touch(exist_ok=True)

        if not self.offset_file.exists() or self.offset_file.stat().st_size == 0:
            self.offset_file.write_text("date,version,offset,total_vectors\n")
        else:
            self.offset_file.touch(exist_ok=True)

    # ── checkpoint ────────────────────────────────────────────────────────────

    async def get(self) -> Checkpoint:
        try:
            with open(self.checkpoint_file, "r") as f:
                lines = [l for l in f.read().splitlines()[1:] if l.strip()]
                if not lines:
                    raise FileNotFoundError
                date, version, last_processed_at = lines[-1].split(",")
                return Checkpoint(
                    version=int(version),
                    last_processed_at=datetime.fromisoformat(last_processed_at)
                )
        except FileNotFoundError:
            return Checkpoint(version=None, last_processed_at=None)

    async def update(self, version: int = None, last_processed_at: datetime = None):
        if version is None:
            logging.info("No version provided, defaulting to 0")
            version = 0

        logging.info(f"Updating checkpoint: v{version + 1}, {last_processed_at.astimezone(self.tz).isoformat()}")
        with open(self.checkpoint_file, "w") as f:
            f.write("date,version,last_processed_at\n")
            f.write(
                f"{datetime.now(self.tz).strftime('%Y-%m-%d %H:%M:%S SGT')}"
                f",{version + 1}"
                f",{last_processed_at.astimezone(self.tz).isoformat()}\n"
            )

    # ── offset ────────────────────────────────────────────────────────────────

    async def get_offset(self) -> OffsetState:
        try:
            with open(self.offset_file, "r") as f:
                lines = [l for l in f.read().splitlines()[1:] if l.strip()]
                if not lines:
                    raise FileNotFoundError
                parts = lines[-1].split(",")
                date, version, offset = parts[0], parts[1], parts[2]
                total_vectors = int(parts[3]) if len(parts) > 3 else 0
                return OffsetState(version=int(version), offset=int(offset), total_vectors=total_vectors)
        except FileNotFoundError:
            return OffsetState(version=None, offset=0, total_vectors=0)

    async def update_offset(self, version: int, offset: int, total_vectors: int = 0):
        logging.debug(f"Offset update: v{version}, offset={offset}, vectors={total_vectors}")
        with open(self.offset_file, "w") as f:
            f.write("date,version,offset,total_vectors_ingested_this_session\n") 
            f.write(
                f"{datetime.now(self.tz).strftime('%Y-%m-%d %H:%M:%S SGT')}"
                f",{version}"
                f",{offset}"
                f",{total_vectors}\n"
            )
