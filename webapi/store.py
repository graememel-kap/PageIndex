from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from .models import PersistedChatSession, PersistedJob, model_dump_compat, model_validate_compat


class JobStore:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.base_dir = repo_root / ".pageindex-web"
        self.jobs_dir = self.base_dir / "jobs"
        self.uploads_dir = self.base_dir / "uploads"
        self.chats_dir = self.base_dir / "chats"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.chats_dir.mkdir(parents=True, exist_ok=True)

    def _job_file(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def save_job(self, job: PersistedJob) -> None:
        out = self._job_file(job.id)
        tmp = out.with_suffix(".json.tmp")
        payload = model_dump_compat(job)
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        tmp.replace(out)

    def load_jobs(self) -> Dict[str, PersistedJob]:
        result: Dict[str, PersistedJob] = {}
        for file in sorted(self.jobs_dir.glob("*.json")):
            with file.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            job = model_validate_compat(PersistedJob, payload)
            result[job.id] = job
        return result

    def _chat_file(self, session_id: str) -> Path:
        return self.chats_dir / f"{session_id}.json"

    def save_session(self, session: PersistedChatSession) -> None:
        out = self._chat_file(session.id)
        tmp = out.with_suffix(".json.tmp")
        payload = model_dump_compat(session)
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        tmp.replace(out)

    def load_sessions(self) -> Dict[str, PersistedChatSession]:
        result: Dict[str, PersistedChatSession] = {}
        for file in sorted(self.chats_dir.glob("*.json")):
            with file.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            session = model_validate_compat(PersistedChatSession, payload)
            result[session.id] = session
        return result

    def load_sessions_by_job(self) -> Dict[str, List[PersistedChatSession]]:
        grouped: Dict[str, List[PersistedChatSession]] = defaultdict(list)
        sessions = self.load_sessions()
        for session in sessions.values():
            grouped[session.job_id].append(session)
        for job_id in grouped:
            grouped[job_id].sort(
                key=lambda item: (item.updated_at, item.created_at),
                reverse=True,
            )
        return dict(grouped)

    def delete_session(self, session_id: str) -> bool:
        path = self._chat_file(session_id)
        if not path.exists():
            return False
        path.unlink()
        return True
