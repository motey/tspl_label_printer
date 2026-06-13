from typing import Optional, Literal, Dict, Generator, Any
from datetime import datetime
from sqlmodel import SQLModel, Field, Column, Session, create_engine
from sqlalchemy import String
from contextlib import contextmanager
from labeljetty.core.sqltypes import SqlJsonText
from labeljetty.config import Config
import uuid
from pathlib import Path
from pydantic import field_serializer, field_validator
from labeljetty.printer import JobType, TSPLPrinterStatusMessage

config = Config()
# Database URL - configure as needed
DATABASE_URL = f"sqlite:///{config.SQLITE_PATH}"

# Create engine
engine = create_engine(DATABASE_URL, echo=False)


class PrintJob(SQLModel, table=True):
    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4, primary_key=True)

    job_type: JobType = Field(
        sa_column=Column(String), description="Which renderer the worker should use"
    )
    # Type-specific parameters (text content, barcode_type, ecc_level, font_size, ...)
    params: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(SqlJsonText),
    )
    # Stored upload for file-based jobs (png/pdf); None for parameter-only jobs.
    input_file_name: Optional[str] = None

    # Per-job label geometry override; None → fall back to config defaults.
    label_width_mm: Optional[int] = None
    label_height_mm: Optional[int] = None
    dpi: Optional[int] = None
    copies: int = 1

    error: Optional[str] = None
    printer_status_on_finished: Optional[TSPLPrinterStatusMessage] = Field(
        default=None,
        sa_column=Column(SqlJsonText),
    )
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    def get_status(self) -> Literal["queued", "processing", "done", "failed"]:
        if self.started_at is None:
            return "queued"
        elif self.finished_at is None:
            return "processing"
        elif self.error is not None:
            return "failed"
        else:
            return "done"

    def get_input_file_path(self) -> Optional[Path]:
        if self.input_file_name is None:
            return None
        return Path(f"{config.IMAGE_STORAGE_DIRECTORY}/{self.input_file_name}")

    @field_serializer("printer_status_on_finished")
    def serialize_printer_status(
        self, value: Optional[TSPLPrinterStatusMessage]
    ) -> Optional[Dict[str, Any]]:
        """Convert TSPLPrinterStatusMessage to dict for database storage"""
        return value.model_dump() if value is not None else None

    @field_validator("printer_status_on_finished", mode="before")
    @classmethod
    def validate_printer_status(cls, value: Dict[str, Any] | None):
        """Convert dict to TSPLPrinterStatusMessage when loading from database"""
        if value is None or isinstance(value, TSPLPrinterStatusMessage):
            return value
        if isinstance(value, dict):
            return TSPLPrinterStatusMessage(**value)
        return value


class WorkerStatus(SQLModel, table=True):
    id: Optional[int] = Field(
        default=1, primary_key=True, description="dummy pk field. Will always be one"
    )
    worker_error: Optional[str] = Field(
        default=None, description="If set the worker is dead"
    )
    process_id: Optional[int] = Field(default=None)


# Database initialization
def init_db():
    """Initialize database tables"""
    SQLModel.metadata.create_all(engine)


# Session management
@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager for database sessions.

    ``expire_on_commit=False`` keeps attributes populated after commit so jobs can
    be safely returned/serialized once the session has closed (FastAPI responses,
    the worker handing a fetched job to the printer).
    """
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_url() -> str:
    """Get database URL"""
    return DATABASE_URL
