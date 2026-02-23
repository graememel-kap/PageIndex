from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .chat_retrieval import (
    build_citations,
    build_tree_prompt_payload,
    flatten_tree,
    get_context_for_nodes,
    select_nodes,
    stream_answer,
)
from .job_manager import JobManager, JobNotFoundError
from .models import (
    ChatEvents,
    ChatMessage,
    ChatMessageCreateResponse,
    ChatRole,
    ChatRun,
    ChatRunStatus,
    ChatSessionDetail,
    ChatSessionSummary,
    JobStatus,
    PersistedChatSession,
    model_dump_compat,
)
from .store import JobStore


class ChatSessionNotFoundError(KeyError):
    pass


class ChatConflictError(RuntimeError):
    pass


class ChatValidationError(ValueError):
    pass


class ChatManager:
    def __init__(self, repo_root: Path, job_manager: JobManager):
        self.repo_root = repo_root
        self.job_manager = job_manager
        self.store = JobStore(repo_root)
        self.sessions: Dict[str, PersistedChatSession] = self.store.load_sessions()
        self.listeners: Dict[Tuple[str, str], List[asyncio.Queue]] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.lock = asyncio.Lock()

        for session in self.sessions.values():
            run = self._active_run(session)
            if run and run.status == ChatRunStatus.RUNNING:
                run.status = ChatRunStatus.FAILED
                run.error = "Backend restarted while chat run was active"
                run.updated_at = self._now_iso()
                session.active_run_id = None
                session.updated_at = self._now_iso()
                self._persist(session)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _new_id(prefix: str = "") -> str:
        token = uuid.uuid4().hex[:12]
        if prefix:
            return f"{prefix}_{token}"
        return token

    def _persist(self, session: PersistedChatSession) -> None:
        session.message_count = len(session.messages)
        if session.messages:
            session.last_message_preview = session.messages[-1].content.strip()[:140] or None
        else:
            session.last_message_preview = None
        active_run = self._active_run(session)
        session.active_run_status = active_run.status if active_run else None
        self.sessions[session.id] = session
        self.store.save_session(session)

    def _active_run(self, session: PersistedChatSession) -> Optional[ChatRun]:
        if not session.active_run_id:
            return None
        for run in session.runs:
            if run.id == session.active_run_id:
                return run
        return None

    def _run_by_id(self, session: PersistedChatSession, run_id: str) -> Optional[ChatRun]:
        for run in session.runs:
            if run.id == run_id:
                return run
        return None

    def _message_by_id(self, session: PersistedChatSession, message_id: str) -> Optional[ChatMessage]:
        for message in session.messages:
            if message.id == message_id:
                return message
        return None

    def _publish(self, session_id: str, run_id: str, event: str, data: Dict[str, Any]) -> None:
        key = (session_id, run_id)
        listeners = self.listeners.get(key, [])
        for queue in list(listeners):
            try:
                queue.put_nowait({"event": event, "data": data})
            except asyncio.QueueFull:
                pass

    def _summary(self, session: PersistedChatSession) -> ChatSessionSummary:
        last_preview = None
        if session.messages:
            last_preview = session.messages[-1].content.strip()[:140] or None
        active_run = self._active_run(session)
        return ChatSessionSummary(
            id=session.id,
            job_id=session.job_id,
            title=session.title,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=len(session.messages),
            last_message_preview=last_preview,
            active_run_id=session.active_run_id,
            active_run_status=active_run.status if active_run else None,
        )

    def _detail(self, session: PersistedChatSession) -> ChatSessionDetail:
        summary = self._summary(session)
        return ChatSessionDetail(
            **model_dump_compat(summary),
            messages=session.messages,
            runs=session.runs,
        )

    def _validate_job_ready(self, job_id: str):
        job = self.job_manager.get_job(job_id)
        if job.status != JobStatus.COMPLETED:
            raise ChatValidationError("Chat is only available for completed jobs")
        if not job.result_file:
            raise FileNotFoundError("Result file not available for this job")
        result_path = Path(job.result_file)
        if not result_path.exists():
            raise FileNotFoundError("Result file is missing on disk")
        return job, result_path

    def get_session(self, session_id: str) -> PersistedChatSession:
        session = self.sessions.get(session_id)
        if not session:
            raise ChatSessionNotFoundError(session_id)
        return session

    def list_sessions(self, job_id: str) -> List[ChatSessionSummary]:
        # Ensure job exists before listing.
        self.job_manager.get_job(job_id)
        sessions = [s for s in self.sessions.values() if s.job_id == job_id]
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return [self._summary(item) for item in sessions]

    def session_detail(self, session_id: str) -> ChatSessionDetail:
        return self._detail(self.get_session(session_id))

    async def create_session(self, job_id: str, title: Optional[str] = None) -> ChatSessionSummary:
        try:
            self._validate_job_ready(job_id)
        except JobNotFoundError:
            raise

        now = self._now_iso()
        session_id = self._new_id("chat")
        session = PersistedChatSession(
            id=session_id,
            job_id=job_id,
            title=(title or "Document Chat").strip() or "Document Chat",
            created_at=now,
            updated_at=now,
            message_count=0,
            last_message_preview=None,
            active_run_id=None,
            active_run_status=None,
            messages=[],
            runs=[],
        )
        async with self.lock:
            self._persist(session)
        return self._summary(session)

    def _remove_session_state(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)
        self.store.delete_session(session_id)
        stale_keys = [key for key in self.listeners if key[0] == session_id]
        for key in stale_keys:
            self.listeners.pop(key, None)

    async def delete_session(self, session_id: str) -> bool:
        async with self.lock:
            session = self.get_session(session_id)
            active = self._active_run(session)
            if active and active.status == ChatRunStatus.RUNNING:
                raise ChatConflictError("Cannot delete a session while a run is active")
            self._remove_session_state(session_id)
            return True

    async def clear_sessions_for_job(self, job_id: str) -> int:
        # Ensure job exists.
        self.job_manager.get_job(job_id)
        async with self.lock:
            targets = [s for s in self.sessions.values() if s.job_id == job_id]
            for session in targets:
                active = self._active_run(session)
                if active and active.status == ChatRunStatus.RUNNING:
                    raise ChatConflictError("Cannot clear sessions while a run is active")
            for session in targets:
                self._remove_session_state(session.id)
            return len(targets)

    async def subscribe(self, session_id: str, run_id: str) -> asyncio.Queue:
        self.get_session(session_id)
        key = (session_id, run_id)
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        async with self.lock:
            self.listeners.setdefault(key, []).append(queue)
        return queue

    async def unsubscribe(self, session_id: str, run_id: str, queue: asyncio.Queue) -> None:
        key = (session_id, run_id)
        async with self.lock:
            listeners = self.listeners.get(key, [])
            if queue in listeners:
                listeners.remove(queue)
            if not listeners and key in self.listeners:
                self.listeners.pop(key, None)

    async def start_message_run(self, session_id: str, content: str) -> ChatMessageCreateResponse:
        trimmed = content.strip()
        if not trimmed:
            raise ChatValidationError("Message content cannot be empty")

        async with self.lock:
            session = self.get_session(session_id)
            active = self._active_run(session)
            if active and active.status == ChatRunStatus.RUNNING:
                raise ChatConflictError("A chat run is already active for this session")

            self._validate_job_ready(session.job_id)

            now = self._now_iso()
            user_message = ChatMessage(
                id=self._new_id("msg"),
                role=ChatRole.USER,
                content=trimmed,
                created_at=now,
                citations=[],
            )
            assistant_message = ChatMessage(
                id=self._new_id("msg"),
                role=ChatRole.ASSISTANT,
                content="",
                created_at=now,
                citations=[],
            )
            run = ChatRun(
                id=self._new_id("run"),
                status=ChatRunStatus.RUNNING,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                created_at=now,
                updated_at=now,
                retrieval_thinking=None,
                selected_node_ids=[],
                error=None,
            )

            session.messages.append(user_message)
            session.messages.append(assistant_message)
            session.runs.append(run)
            session.active_run_id = run.id
            session.updated_at = now
            self._persist(session)

            self._publish(
                session_id,
                run.id,
                ChatEvents.RUN_STARTED,
                {
                    "session_id": session_id,
                    "run_id": run.id,
                    "user_message_id": user_message.id,
                    "assistant_message_id": assistant_message.id,
                    "timestamp": now,
                },
            )

            task = asyncio.create_task(
                self._run_pipeline(
                    session_id=session_id,
                    run_id=run.id,
                    query=trimmed,
                )
            )
            self.tasks[run.id] = task

            return ChatMessageCreateResponse(
                run_id=run.id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
            )

    async def _run_pipeline(self, session_id: str, run_id: str, query: str) -> None:
        try:
            async with self.lock:
                session = self.get_session(session_id)
                run = self._run_by_id(session, run_id)
                if not run:
                    return
                user_message = self._message_by_id(session, run.user_message_id)
                assistant_message = self._message_by_id(session, run.assistant_message_id)
                if not user_message or not assistant_message:
                    raise ChatValidationError("Run messages are missing")
                user_index = next(
                    (idx for idx, msg in enumerate(session.messages) if msg.id == user_message.id),
                    -1,
                )
                history_snapshot = session.messages[:user_index] if user_index >= 0 else []
                job, result_path = self._validate_job_ready(session.job_id)
                model = str(job.options.get("model") or "gpt-4.1")

            with result_path.open("r", encoding="utf-8") as f:
                result_payload = json.load(f)
            structure = result_payload.get("structure")
            if not isinstance(structure, list):
                raise ChatValidationError("Invalid result structure; expected top-level list")

            node_map = flatten_tree(structure)
            tree_payload = build_tree_prompt_payload(structure)
            thinking, selected_node_ids = await select_nodes(
                query=query,
                history=history_snapshot,
                tree_payload=tree_payload,
                valid_node_ids=node_map.keys(),
                model=model,
            )

            async with self.lock:
                session = self.get_session(session_id)
                run = self._run_by_id(session, run_id)
                if not run:
                    return
                run.retrieval_thinking = thinking
                run.selected_node_ids = selected_node_ids
                run.updated_at = self._now_iso()
                self._persist(session)

                citations_payload = [
                    citation.model_dump() if hasattr(citation, "model_dump") else citation.dict()
                    for citation in build_citations(selected_node_ids, node_map)
                ]
                self._publish(
                    session_id,
                    run_id,
                    ChatEvents.RETRIEVAL_COMPLETED,
                    {
                        "session_id": session_id,
                        "run_id": run_id,
                        "thinking": thinking,
                        "node_ids": selected_node_ids,
                        "citations": citations_payload,
                        "timestamp": self._now_iso(),
                    },
                )

            context_nodes = get_context_for_nodes(
                job=job,
                node_ids=selected_node_ids,
                node_map=node_map,
            )

            async def on_delta(delta: str) -> None:
                async with self.lock:
                    session_inner = self.get_session(session_id)
                    assistant_inner = self._message_by_id(
                        session_inner, run.assistant_message_id
                    )
                    if assistant_inner is None:
                        return
                    assistant_inner.content += delta
                    session_inner.updated_at = self._now_iso()
                    self._publish(
                        session_id,
                        run_id,
                        ChatEvents.ANSWER_DELTA,
                        {
                            "session_id": session_id,
                            "run_id": run_id,
                            "assistant_message_id": run.assistant_message_id,
                            "delta": delta,
                            "timestamp": self._now_iso(),
                        },
                    )

            final_answer = await stream_answer(
                query=query,
                history=history_snapshot,
                context_nodes=context_nodes,
                model=model,
                on_delta=on_delta,
            )

            async with self.lock:
                session = self.get_session(session_id)
                run = self._run_by_id(session, run_id)
                assistant_message = self._message_by_id(session, run.assistant_message_id) if run else None
                if not run or not assistant_message:
                    return

                assistant_message.content = final_answer
                assistant_message.citations = build_citations(selected_node_ids, node_map)
                run.status = ChatRunStatus.COMPLETED
                run.updated_at = self._now_iso()
                session.active_run_id = None
                session.updated_at = self._now_iso()
                self._persist(session)

                self._publish(
                    session_id,
                    run_id,
                    ChatEvents.ANSWER_COMPLETED,
                    {
                        "session_id": session_id,
                        "run_id": run_id,
                        "assistant_message_id": assistant_message.id,
                        "citations": [
                            citation.model_dump() if hasattr(citation, "model_dump") else citation.dict()
                            for citation in assistant_message.citations
                        ],
                        "timestamp": self._now_iso(),
                    },
                )
                self._publish(
                    session_id,
                    run_id,
                    ChatEvents.RUN_COMPLETED,
                    {
                        "session_id": session_id,
                        "run_id": run_id,
                        "timestamp": self._now_iso(),
                    },
                )
        except Exception as exc:
            async with self.lock:
                session = self.sessions.get(session_id)
                if session:
                    run = self._run_by_id(session, run_id)
                    if run:
                        run.status = ChatRunStatus.FAILED
                        run.error = str(exc)
                        run.updated_at = self._now_iso()
                        session.active_run_id = None
                        session.updated_at = self._now_iso()
                        self._persist(session)
                    self._publish(
                        session_id,
                        run_id,
                        ChatEvents.RUN_FAILED,
                        {
                            "session_id": session_id,
                            "run_id": run_id,
                            "error": str(exc),
                            "timestamp": self._now_iso(),
                        },
                    )
        finally:
            self.tasks.pop(run_id, None)
