from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from .models import PersistedJob, model_dump_compat, model_validate_compat


class JobStore:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.base_dir = repo_root / ".pageindex-web"
        self.jobs_dir = self.base_dir / "jobs"
        self.uploads_dir = self.base_dir / "uploads"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

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
