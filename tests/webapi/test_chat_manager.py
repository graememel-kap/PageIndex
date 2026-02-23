import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from webapi.chat_manager import ChatManager
from webapi.job_manager import JobManager
from webapi.main import create_app
from webapi.models import JobStage, JobStatus, PersistedJob


def make_job(
    *,
    job_id: str,
    input_path: str,
    status: JobStatus,
    result_file: str | None,
) -> PersistedJob:
    stage = JobStage.COMPLETED if status == JobStatus.COMPLETED else JobStage.INDEX_BUILD
    progress = 1.0 if status == JobStatus.COMPLETED else 0.5
    return PersistedJob(
        id=job_id,
        filename=Path(input_path).name,
        input_type="pdf",
        status=status,
        stage=stage,
        progress=progress,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        options={"model": "gpt-4.1"},
        input_path=input_path,
        log_file=None,
        result_file=result_file,
        error=None,
        stdout_tail=[],
        activity=[],
        pid=None,
    )


class ChatManagerIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_pipeline_persists_assistant_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pageindex-web" / "uploads").mkdir(parents=True, exist_ok=True)
            (root / "results").mkdir(parents=True, exist_ok=True)

            input_pdf = root / ".pageindex-web" / "uploads" / "doc.pdf"
            input_pdf.write_bytes(b"%PDF-1.4\n")

            result_path = root / "results" / "doc_structure.json"
            result_path.write_text(
                """
                {
                  "doc_name": "doc.pdf",
                  "structure": [
                    {
                      "title": "Section A",
                      "node_id": "0001",
                      "start_index": 1,
                      "end_index": 1,
                      "text": "Revenue was 10 million."
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )

            job_manager = JobManager(repo_root=root)
            job = make_job(
                job_id="job_ok",
                input_path=str(input_pdf),
                status=JobStatus.COMPLETED,
                result_file=str(result_path),
            )
            job_manager.jobs[job.id] = job
            chat_manager = ChatManager(repo_root=root, job_manager=job_manager)

            captured_events: list[str] = []
            original_publish = chat_manager._publish

            def capture_publish(session_id, run_id, event, data):
                captured_events.append(event)
                original_publish(session_id, run_id, event, data)

            async def fake_select_nodes(**kwargs):
                return "Node 0001 likely contains the answer.", ["0001"]

            async def fake_stream_answer(**kwargs):
                on_delta = kwargs["on_delta"]
                await on_delta("Revenue was 10 million. ")
                await on_delta("Sources: node 0001 (pages 1-1).")
                return "Revenue was 10 million. Sources: node 0001 (pages 1-1)."

            with patch.object(chat_manager, "_publish", side_effect=capture_publish), patch(
                "webapi.chat_manager.select_nodes", side_effect=fake_select_nodes
            ), patch("webapi.chat_manager.stream_answer", side_effect=fake_stream_answer):
                session = await chat_manager.create_session(job_id=job.id)
                started = await chat_manager.start_message_run(
                    session_id=session.id,
                    content="What is revenue?",
                )
                await chat_manager.tasks[started.run_id]

            detail = chat_manager.session_detail(session.id)
            assistant = [m for m in detail.messages if m.role.value == "assistant"][-1]
            self.assertIn("Revenue was 10 million", assistant.content)
            self.assertGreaterEqual(len(assistant.citations), 1)
            self.assertIn("chat.run.started", captured_events)
            self.assertIn("chat.retrieval.completed", captured_events)
            self.assertIn("chat.answer.delta", captured_events)
            self.assertIn("chat.answer.completed", captured_events)
            self.assertIn("chat.run.completed", captured_events)

    async def test_clear_sessions_for_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pageindex-web" / "uploads").mkdir(parents=True, exist_ok=True)
            (root / "results").mkdir(parents=True, exist_ok=True)
            input_pdf = root / ".pageindex-web" / "uploads" / "doc.pdf"
            input_pdf.write_bytes(b"%PDF-1.4\n")
            result_path = root / "results" / "doc_structure.json"
            result_path.write_text(
                '{"doc_name":"doc.pdf","structure":[]}',
                encoding="utf-8",
            )

            job_manager = JobManager(repo_root=root)
            job = make_job(
                job_id="job_ok",
                input_path=str(input_pdf),
                status=JobStatus.COMPLETED,
                result_file=str(result_path),
            )
            job_manager.jobs[job.id] = job
            chat_manager = ChatManager(repo_root=root, job_manager=job_manager)

            s1 = await chat_manager.create_session(job_id=job.id)
            s2 = await chat_manager.create_session(job_id=job.id)
            self.assertEqual(len(chat_manager.list_sessions(job.id)), 2)

            deleted = await chat_manager.clear_sessions_for_job(job.id)
            self.assertEqual(deleted, 2)
            self.assertEqual(len(chat_manager.list_sessions(job.id)), 0)
            with self.assertRaises(Exception):
                chat_manager.get_session(s1.id)
            with self.assertRaises(Exception):
                chat_manager.get_session(s2.id)


class ChatApiRejectionTest(unittest.TestCase):
    def test_chat_session_rejects_non_completed_or_missing_result(self):
        app = create_app()
        manager: JobManager = app.state.job_manager

        running_job = make_job(
            job_id="job_running",
            input_path="/tmp/a.pdf",
            status=JobStatus.RUNNING,
            result_file=None,
        )
        completed_missing = make_job(
            job_id="job_completed_missing",
            input_path="/tmp/b.pdf",
            status=JobStatus.COMPLETED,
            result_file=None,
        )
        manager.jobs[running_job.id] = running_job
        manager.jobs[completed_missing.id] = completed_missing

        client = TestClient(app)

        res_running = client.post("/api/jobs/job_running/chat/sessions")
        self.assertEqual(res_running.status_code, 409)

        res_missing = client.post("/api/jobs/job_completed_missing/chat/sessions")
        self.assertEqual(res_missing.status_code, 404)

    def test_clear_sessions_endpoint(self):
        app = create_app()
        manager: JobManager = app.state.job_manager

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_pdf = tmp_path / "doc.pdf"
            input_pdf.write_bytes(b"%PDF-1.4\n")
            result_path = tmp_path / "doc_structure.json"
            result_path.write_text('{"doc_name":"doc.pdf","structure":[]}', encoding="utf-8")

            job = make_job(
                job_id="job_ok",
                input_path=str(input_pdf),
                status=JobStatus.COMPLETED,
                result_file=str(result_path),
            )
            manager.jobs[job.id] = job

            client = TestClient(app)
            created = client.post("/api/jobs/job_ok/chat/sessions")
            self.assertEqual(created.status_code, 201)

            cleared = client.delete("/api/jobs/job_ok/chat/sessions")
            self.assertEqual(cleared.status_code, 200)
            self.assertEqual(cleared.json()["deleted_count"], 1)


if __name__ == "__main__":
    unittest.main()
