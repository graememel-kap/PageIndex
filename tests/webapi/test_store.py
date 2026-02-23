import json
import tempfile
import unittest
from pathlib import Path

from webapi.models import (
    ChatMessage,
    ChatRole,
    ChatRun,
    ChatRunStatus,
    JobStage,
    JobStatus,
    PersistedChatSession,
    PersistedJob,
)
from webapi.store import JobStore


class JobStoreTest(unittest.TestCase):
    def test_save_and_load_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = JobStore(root)
            job = PersistedJob(
                id="abc123",
                filename="doc.pdf",
                input_type="pdf",
                status=JobStatus.QUEUED,
                stage=JobStage.QUEUED,
                progress=0.05,
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
                options={"model": "gpt-4.1"},
                input_path=str(root / "upload.pdf"),
                log_file=None,
                result_file=None,
                error=None,
                stdout_tail=[],
                activity=[],
                pid=None,
            )

            store.save_job(job)
            loaded = store.load_jobs()

            self.assertIn("abc123", loaded)
            self.assertEqual(loaded["abc123"].filename, "doc.pdf")
            self.assertEqual(loaded["abc123"].options["model"], "gpt-4.1")

            # Ensure persisted JSON exists and is parseable.
            with (store.jobs_dir / "abc123.json").open("r", encoding="utf-8") as f:
                payload = json.load(f)
            self.assertEqual(payload["id"], "abc123")

    def test_save_and_load_chat_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = JobStore(root)

            session = PersistedChatSession(
                id="chat_123",
                job_id="job_123",
                title="Document Chat",
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
                message_count=2,
                last_message_preview="hello",
                active_run_id=None,
                active_run_status=None,
                messages=[
                    ChatMessage(
                        id="msg_1",
                        role=ChatRole.USER,
                        content="hello",
                        created_at="2026-01-01T00:00:00Z",
                        citations=[],
                    )
                ],
                runs=[
                    ChatRun(
                        id="run_1",
                        status=ChatRunStatus.COMPLETED,
                        user_message_id="msg_1",
                        assistant_message_id="msg_2",
                        created_at="2026-01-01T00:00:00Z",
                        updated_at="2026-01-01T00:00:01Z",
                        retrieval_thinking="sample",
                        selected_node_ids=["0001"],
                        error=None,
                    )
                ],
            )

            store.save_session(session)
            loaded = store.load_sessions()
            grouped = store.load_sessions_by_job()

            self.assertIn("chat_123", loaded)
            self.assertEqual(loaded["chat_123"].job_id, "job_123")
            self.assertIn("job_123", grouped)
            self.assertEqual(grouped["job_123"][0].id, "chat_123")
            self.assertTrue(store.delete_session("chat_123"))
            self.assertFalse(store.delete_session("chat_123"))


if __name__ == "__main__":
    unittest.main()
