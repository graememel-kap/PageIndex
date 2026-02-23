from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobStage(str, Enum):
    QUEUED = "QUEUED"
    PARSING_INPUT = "PARSING_INPUT"
    TOC_ANALYSIS = "TOC_ANALYSIS"
    INDEX_BUILD = "INDEX_BUILD"
    REFINEMENT = "REFINEMENT"
    SUMMARIZATION = "SUMMARIZATION"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"


class ActivityItem(BaseModel):
    timestamp: str
    source: Literal["stdout", "stderr", "log", "system"]
    message: str


class JobSummary(BaseModel):
    id: str
    filename: str
    input_type: Literal["pdf", "md"]
    status: JobStatus
    stage: JobStage
    progress: float
    created_at: str
    updated_at: str


class JobDetail(JobSummary):
    options: Dict[str, Any] = Field(default_factory=dict)
    input_path: str
    log_file: Optional[str] = None
    result_file: Optional[str] = None
    error: Optional[str] = None
    stdout_tail: List[str] = Field(default_factory=list)
    activity: List[ActivityItem] = Field(default_factory=list)
    pid: Optional[int] = None


class PersistedJob(JobDetail):
    pass


def model_dump_compat(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def model_validate_compat(cls, payload: Dict[str, Any]):
    if hasattr(cls, "model_validate"):
        return cls.model_validate(payload)
    return cls.parse_obj(payload)
