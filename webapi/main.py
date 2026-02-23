from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from .job_manager import JobConflictError, JobManager, JobNotFoundError
from .models import JobDetail, JobSummary


def _clean_options(options: Dict[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for key, value in options.items():
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        clean[key] = value
    return clean


def create_app() -> FastAPI:
    repo_root = Path(__file__).resolve().parents[1]
    manager = JobManager(repo_root=repo_root)

    app = FastAPI(title="PageIndex Web API", version="0.1.0")
    app.state.job_manager = manager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/jobs", response_model=JobSummary, status_code=201)
    async def create_job(
        file: UploadFile = File(...),
        input_type: Literal["pdf", "md"] = Form(...),
        model: Optional[str] = Form(None),
        toc_check_pages: Optional[int] = Form(None),
        max_pages_per_node: Optional[int] = Form(None),
        max_tokens_per_node: Optional[int] = Form(None),
        if_add_node_id: Optional[Literal["yes", "no"]] = Form(None),
        if_add_node_summary: Optional[Literal["yes", "no"]] = Form(None),
        if_add_doc_description: Optional[Literal["yes", "no"]] = Form(None),
        if_add_node_text: Optional[Literal["yes", "no"]] = Form(None),
        if_thinning: Optional[Literal["yes", "no"]] = Form(None),
        thinning_threshold: Optional[int] = Form(None),
        summary_token_threshold: Optional[int] = Form(None),
    ) -> JobSummary:
        options = _clean_options(
            {
                "model": model,
                "toc_check_pages": toc_check_pages,
                "max_pages_per_node": max_pages_per_node,
                "max_tokens_per_node": max_tokens_per_node,
                "if_add_node_id": if_add_node_id,
                "if_add_node_summary": if_add_node_summary,
                "if_add_doc_description": if_add_doc_description,
                "if_add_node_text": if_add_node_text,
                "if_thinning": if_thinning,
                "thinning_threshold": thinning_threshold,
                "summary_token_threshold": summary_token_threshold,
            }
        )

        try:
            job = await manager.create_job(file, input_type=input_type, options=options)
            return manager.summary(job)
        except JobConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/jobs", response_model=List[JobSummary])
    async def list_jobs() -> List[JobSummary]:
        return [manager.summary(item) for item in manager.list_jobs()]

    @app.get("/api/jobs/{job_id}", response_model=JobDetail)
    async def get_job(job_id: str) -> JobDetail:
        try:
            return manager.detail(manager.get_job(job_id))
        except JobNotFoundError:
            raise HTTPException(status_code=404, detail="Job not found")

    @app.get("/api/jobs/{job_id}/events")
    async def stream_job_events(job_id: str) -> EventSourceResponse:
        try:
            queue = await manager.subscribe(job_id)
        except JobNotFoundError:
            raise HTTPException(status_code=404, detail="Job not found")

        async def event_publisher():
            try:
                while True:
                    payload = await queue.get()
                    yield {
                        "event": payload["event"],
                        "data": json.dumps(payload["data"], ensure_ascii=False),
                    }
            finally:
                await manager.unsubscribe(job_id, queue)

        return EventSourceResponse(event_publisher(), ping=10)

    @app.post("/api/jobs/{job_id}/cancel", response_model=JobDetail)
    async def cancel_job(job_id: str) -> JobDetail:
        try:
            job = await manager.cancel_job(job_id)
            return manager.detail(job)
        except JobNotFoundError:
            raise HTTPException(status_code=404, detail="Job not found")

    @app.get("/api/jobs/{job_id}/result")
    async def get_job_result(job_id: str):
        try:
            job = manager.get_job(job_id)
        except JobNotFoundError:
            raise HTTPException(status_code=404, detail="Job not found")

        if not job.result_file:
            raise HTTPException(status_code=404, detail="Result file not available")

        path = Path(job.result_file)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Result file missing")

        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return JSONResponse(payload)

    return app


app = create_app()
