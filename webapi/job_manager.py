from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import UploadFile

from .models import ActivityItem, JobDetail, JobStage, JobStatus, JobSummary, PersistedJob
from .progress import STAGE_PROGRESS, stage_from_log_entry, stage_from_text, stage_rank
from .store import JobStore


class JobNotFoundError(KeyError):
    pass


class JobConflictError(RuntimeError):
    pass


class JobManager:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.logs_dir = repo_root / "logs"
        self.results_dir = repo_root / "results"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.store = JobStore(repo_root)

        self.jobs: Dict[str, PersistedJob] = self.store.load_jobs()
        self.listeners: Dict[str, List[asyncio.Queue]] = {}
        self.processes: Dict[str, asyncio.subprocess.Process] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.lock = asyncio.Lock()

        self.active_job_id: Optional[str] = None
        for job in self.jobs.values():
            if job.status == JobStatus.RUNNING:
                job.status = JobStatus.FAILED
                job.error = "Backend restarted while job was running"
                job.updated_at = self._now_iso()
                self.store.save_job(job)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_filename(name: str) -> str:
        keep = []
        for ch in name:
            if ch.isalnum() or ch in ("-", "_", "."):
                keep.append(ch)
            elif ch in (" ", "/"):
                keep.append("_")
        cleaned = "".join(keep).strip("._")
        return cleaned or "document"

    def _persist(self, job: PersistedJob) -> None:
        self.jobs[job.id] = job
        self.store.save_job(job)

    def _publish(self, job_id: str, event: str, data: Dict[str, Any]) -> None:
        listeners = self.listeners.get(job_id, [])
        for queue in list(listeners):
            try:
                queue.put_nowait({"event": event, "data": data})
            except asyncio.QueueFull:
                pass

    def _emit_update(self, job: PersistedJob) -> None:
        self._publish(job.id, "job.update", {"job": job.model_dump() if hasattr(job, "model_dump") else job.dict()})

    def _append_stdout_tail(self, job: PersistedJob, source: str, message: str) -> None:
        job.stdout_tail.append(f"[{source}] {message}")
        if len(job.stdout_tail) > 300:
            job.stdout_tail = job.stdout_tail[-300:]

    def _append_activity(self, job: PersistedJob, source: Literal["stdout", "stderr", "log", "system"], message: str) -> None:
        item = ActivityItem(timestamp=self._now_iso(), source=source, message=message)
        job.activity.append(item)
        if len(job.activity) > 400:
            job.activity = job.activity[-400:]
        self._publish(job.id, "job.activity", {"job_id": job.id, "activity": item.model_dump() if hasattr(item, "model_dump") else item.dict()})

    def _advance_stage(self, job: PersistedJob, new_stage: Optional[JobStage], reason: str) -> bool:
        if new_stage is None:
            return False
        if stage_rank(new_stage) <= stage_rank(job.stage):
            return False
        job.stage = new_stage
        job.progress = STAGE_PROGRESS[new_stage]
        job.updated_at = self._now_iso()
        self._append_activity(job, "system", f"Stage -> {new_stage.value}: {reason}")
        self._persist(job)
        self._emit_update(job)
        return True

    def _finalize(self, job: PersistedJob, status: JobStatus, *, error: Optional[str] = None) -> None:
        job.status = status
        job.updated_at = self._now_iso()
        if error:
            job.error = error
            self._publish(job.id, "job.error", {"job_id": job.id, "error": error, "timestamp": self._now_iso()})

        if status == JobStatus.COMPLETED:
            job.stage = JobStage.COMPLETED
            job.progress = STAGE_PROGRESS[JobStage.COMPLETED]

        self._persist(job)
        if status == JobStatus.COMPLETED:
            self._publish(
                job.id,
                "job.completed",
                {
                    "job_id": job.id,
                    "timestamp": self._now_iso(),
                    "result_file": job.result_file,
                },
            )
        self._emit_update(job)

    def _build_command(self, job: PersistedJob) -> List[str]:
        options = dict(job.options)
        cmd = ["python3", str(self.repo_root / "run_pageindex.py")]
        if job.input_type == "pdf":
            cmd.extend(["--pdf_path", job.input_path])
        else:
            cmd.extend(["--md_path", job.input_path])

        arg_map = {
            "model": "--model",
            "toc_check_pages": "--toc-check-pages",
            "max_pages_per_node": "--max-pages-per-node",
            "max_tokens_per_node": "--max-tokens-per-node",
            "if_add_node_id": "--if-add-node-id",
            "if_add_node_summary": "--if-add-node-summary",
            "if_add_doc_description": "--if-add-doc-description",
            "if_add_node_text": "--if-add-node-text",
            "if_thinning": "--if-thinning",
            "thinning_threshold": "--thinning-threshold",
            "summary_token_threshold": "--summary-token-threshold",
        }

        for key, arg_name in arg_map.items():
            value = options.get(key)
            if value is None or value == "":
                continue
            cmd.extend([arg_name, str(value)])

        return cmd

    async def _detect_log_file(
        self,
        before: set[str],
        process: asyncio.subprocess.Process,
        timeout_s: float = 20.0,
    ) -> Optional[Path]:
        deadline = asyncio.get_running_loop().time() + timeout_s
        post_exit_checks = 0
        while asyncio.get_running_loop().time() < deadline:
            after = {p.name for p in self.logs_dir.glob("*.json")}
            new_files = sorted(after - before)
            if new_files:
                return self.logs_dir / new_files[-1]
            if process.returncode is not None:
                post_exit_checks += 1
                if post_exit_checks >= 2:
                    return None
            await asyncio.sleep(0.4)
        return None

    async def _consume_stream(
        self,
        job_id: str,
        stream: asyncio.StreamReader,
        source: Literal["stdout", "stderr"],
    ) -> None:
        job = self.jobs[job_id]
        while True:
            line = await stream.readline()
            if not line:
                break
            message = line.decode(errors="replace").rstrip("\n")
            if not message:
                continue
            self._append_stdout_tail(job, source, message)
            self._append_activity(job, source, message)
            stage = stage_from_text(message)
            self._advance_stage(job, stage, f"signal from {source}")
            if "tree structure saved to:" in message.lower():
                parts = message.split(":", 1)
                if len(parts) == 2:
                    result_rel = parts[1].strip()
                    if result_rel:
                        candidate = (self.repo_root / result_rel).resolve() if not os.path.isabs(result_rel) else Path(result_rel)
                        job.result_file = str(candidate)
            job.updated_at = self._now_iso()
            self._persist(job)
            self._emit_update(job)

    async def _consume_log_file(self, job_id: str, log_file: Path, process: asyncio.subprocess.Process) -> None:
        job = self.jobs[job_id]
        parsed_count = 0
        post_exit_polls = 0

        while True:
            if log_file.exists():
                try:
                    with log_file.open("r", encoding="utf-8") as f:
                        content = json.load(f)
                    if isinstance(content, list) and len(content) > parsed_count:
                        new_entries = content[parsed_count:]
                        parsed_count = len(content)
                        for entry in new_entries:
                            stage = stage_from_log_entry(entry)
                            if isinstance(entry, dict):
                                log_message = json.dumps(entry, ensure_ascii=False)
                            else:
                                log_message = str(entry)
                            self._append_activity(job, "log", log_message)
                            self._advance_stage(job, stage, "signal from log")
                        job.updated_at = self._now_iso()
                        self._persist(job)
                        self._emit_update(job)
                except (json.JSONDecodeError, OSError):
                    pass

            if process.returncode is not None:
                post_exit_polls += 1
                if post_exit_polls >= 4:
                    break
            await asyncio.sleep(0.5)

    async def _run_job(self, job_id: str) -> None:
        job = self.jobs[job_id]
        before_logs = {p.name for p in self.logs_dir.glob("*.json")}
        cmd = self._build_command(job)

        job.status = JobStatus.RUNNING
        job.updated_at = self._now_iso()
        self._append_activity(job, "system", f"Launching: {' '.join(cmd)}")
        self._persist(job)
        self._emit_update(job)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.repo_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self.processes[job_id] = process
        job.pid = process.pid
        job.updated_at = self._now_iso()
        self._persist(job)
        self._emit_update(job)

        stdout_task = asyncio.create_task(self._consume_stream(job_id, process.stdout, "stdout"))
        stderr_task = asyncio.create_task(self._consume_stream(job_id, process.stderr, "stderr"))

        log_file = await self._detect_log_file(before_logs, process)
        log_task: Optional[asyncio.Task] = None
        if log_file is not None:
            job.log_file = str(log_file.resolve())
            job.updated_at = self._now_iso()
            self._append_activity(job, "system", f"Attached log file: {job.log_file}")
            self._persist(job)
            self._emit_update(job)
            log_task = asyncio.create_task(self._consume_log_file(job_id, log_file, process))

        return_code = await process.wait()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        if log_task is not None:
            await asyncio.gather(log_task, return_exceptions=True)

        self.processes.pop(job_id, None)

        # Job may already be cancelled via cancel_job.
        if job.status == JobStatus.CANCELLED:
            async with self.lock:
                if self.active_job_id == job_id:
                    self.active_job_id = None
            self.tasks.pop(job_id, None)
            self._persist(job)
            self._emit_update(job)
            return

        result_name = f"{Path(job.input_path).stem}_structure.json"
        expected_result = (self.results_dir / result_name).resolve()
        if expected_result.exists():
            job.result_file = str(expected_result)

        if return_code == 0 and job.result_file and Path(job.result_file).exists():
            self._advance_stage(job, JobStage.FINALIZING, "subprocess exited successfully")
            self._finalize(job, JobStatus.COMPLETED)
        else:
            error = job.error
            if not error:
                stderr_lines = [line for line in job.stdout_tail if line.startswith("[stderr]")]
                if stderr_lines:
                    error = stderr_lines[-1]
                elif return_code != 0:
                    error = f"Process exited with code {return_code}"
                else:
                    error = "Process completed but no result file was found"
            self._finalize(job, JobStatus.FAILED, error=error)

        async with self.lock:
            if self.active_job_id == job_id:
                self.active_job_id = None
        self.tasks.pop(job_id, None)

    async def create_job(
        self,
        upload_file: UploadFile,
        input_type: Literal["pdf", "md"],
        options: Dict[str, Any],
    ) -> PersistedJob:
        filename = upload_file.filename or "document"
        safe_name = self._safe_filename(filename)
        suffix = Path(safe_name).suffix.lower()

        if input_type == "pdf" and suffix != ".pdf":
            raise ValueError("input_type=pdf requires a .pdf file")
        if input_type == "md" and suffix not in (".md", ".markdown"):
            raise ValueError("input_type=md requires a .md or .markdown file")

        async with self.lock:
            if self.active_job_id is not None:
                active = self.jobs.get(self.active_job_id)
                if active and active.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                    raise JobConflictError("A job is already running")

            now = self._now_iso()
            job_id = uuid.uuid4().hex[:12]
            input_path = self.store.uploads_dir / f"{job_id}_{safe_name}"

            with input_path.open("wb") as f:
                while True:
                    chunk = await upload_file.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)

            job = PersistedJob(
                id=job_id,
                filename=filename,
                input_type=input_type,
                status=JobStatus.QUEUED,
                stage=JobStage.QUEUED,
                progress=STAGE_PROGRESS[JobStage.QUEUED],
                created_at=now,
                updated_at=now,
                options=options,
                input_path=str(input_path.resolve()),
                log_file=None,
                result_file=None,
                error=None,
                stdout_tail=[],
                activity=[],
                pid=None,
            )
            self._append_activity(job, "system", "Job created")
            self._persist(job)
            self.active_job_id = job_id
            self._emit_update(job)

            task = asyncio.create_task(self._run_job(job_id))
            self.tasks[job_id] = task

            return job

    async def cancel_job(self, job_id: str) -> PersistedJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)

        proc = self.processes.get(job_id)
        if proc is None or proc.returncode is not None:
            return job

        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=6)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

        job.status = JobStatus.CANCELLED
        job.updated_at = self._now_iso()
        self._append_activity(job, "system", "Job cancelled by user")
        self._persist(job)
        self._emit_update(job)

        async with self.lock:
            if self.active_job_id == job_id:
                self.active_job_id = None

        return job

    async def subscribe(self, job_id: str) -> asyncio.Queue:
        job = self.jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)

        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.listeners.setdefault(job_id, []).append(queue)
        self._publish(job_id, "job.update", {"job": job.model_dump() if hasattr(job, "model_dump") else job.dict()})
        return queue

    async def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        listeners = self.listeners.get(job_id, [])
        if queue in listeners:
            listeners.remove(queue)

    def get_job(self, job_id: str) -> PersistedJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    def list_jobs(self) -> List[PersistedJob]:
        return sorted(
            self.jobs.values(),
            key=lambda item: item.created_at,
            reverse=True,
        )

    def summary(self, job: PersistedJob) -> JobSummary:
        return JobSummary(
            id=job.id,
            filename=job.filename,
            input_type=job.input_type,
            status=job.status,
            stage=job.stage,
            progress=job.progress,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    def detail(self, job: PersistedJob) -> JobDetail:
        return JobDetail(**(job.model_dump() if hasattr(job, "model_dump") else job.dict()))
