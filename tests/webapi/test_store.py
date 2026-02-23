import json
import tempfile
import unittest
from pathlib import Path

from webapi.models import JobStage, JobStatus, PersistedJob
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


if __name__ == "__main__":
    unittest.main()
