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


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatRunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class NodeCitation(BaseModel):
    node_id: str
    title: Optional[str] = None
    start_index: Optional[int] = None
    end_index: Optional[int] = None
    line_num: Optional[int] = None


class ChatMessage(BaseModel):
    id: str
    role: ChatRole
    content: str
    created_at: str
    citations: List[NodeCitation] = Field(default_factory=list)


class ChatRun(BaseModel):
    id: str
    status: ChatRunStatus
    user_message_id: str
    assistant_message_id: str
    created_at: str
    updated_at: str
    retrieval_thinking: Optional[str] = None
    selected_node_ids: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class ChatSessionSummary(BaseModel):
    id: str
    job_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0
    last_message_preview: Optional[str] = None
    active_run_id: Optional[str] = None
    active_run_status: Optional[ChatRunStatus] = None


class ChatSessionDetail(ChatSessionSummary):
    messages: List[ChatMessage] = Field(default_factory=list)
    runs: List[ChatRun] = Field(default_factory=list)


class PersistedChatSession(ChatSessionDetail):
    pass


class ChatMessageCreateRequest(BaseModel):
    content: str = Field(min_length=1)


class ChatMessageCreateResponse(BaseModel):
    run_id: str
    user_message_id: str
    assistant_message_id: str


class ChatSessionsClearResponse(BaseModel):
    deleted_count: int


class ChatEvents:
    RUN_STARTED = "chat.run.started"
    RETRIEVAL_COMPLETED = "chat.retrieval.completed"
    ANSWER_DELTA = "chat.answer.delta"
    ANSWER_COMPLETED = "chat.answer.completed"
    RUN_COMPLETED = "chat.run.completed"
    RUN_FAILED = "chat.run.failed"


def model_dump_compat(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def model_validate_compat(cls, payload: Dict[str, Any]):
    if hasattr(cls, "model_validate"):
        return cls.model_validate(payload)
    return cls.parse_obj(payload)
