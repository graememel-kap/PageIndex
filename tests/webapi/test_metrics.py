import importlib.util
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load utils directly to avoid heavy optional dependencies in page_index.py
_utils_spec = importlib.util.spec_from_file_location(
    "pageindex_utils", ROOT / "pageindex" / "utils.py"
)
_utils_mod = importlib.util.module_from_spec(_utils_spec)


class IndexingMetricsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Provide stub modules so utils.py can be imported without all deps
        for stub in ("tiktoken", "openai", "PyPDF2", "pymupdf", "dotenv", "yaml"):
            if stub not in sys.modules:
                sys.modules[stub] = type(sys)("stub_" + stub)
        # dotenv needs load_dotenv
        sys.modules["dotenv"].load_dotenv = lambda: None
        # yaml needs safe_load
        sys.modules["yaml"].safe_load = lambda f: {}
        _utils_spec.loader.exec_module(_utils_mod)

    def _make_metrics(self):
        return _utils_mod.IndexingMetrics()

    def test_summary_includes_total_duration(self):
        m = self._make_metrics()
        summary = m.summary()
        self.assertIn("total_duration_s", summary)
        self.assertGreaterEqual(summary["total_duration_s"], 0.0)

    def test_summary_type_field(self):
        m = self._make_metrics()
        self.assertEqual(m.summary()["type"], "metrics_summary")

    def test_phase_timing_recorded(self):
        m = self._make_metrics()
        m.start_phase("test_phase")
        time.sleep(0.05)
        duration = m.end_phase("test_phase")
        self.assertGreater(duration, 0.0)
        self.assertIn("test_phase", m.phases)
        self.assertEqual(m.phases["test_phase"], duration)

    def test_summary_contains_phases(self):
        m = self._make_metrics()
        m.start_phase("phase_a")
        m.end_phase("phase_a")
        m.start_phase("phase_b")
        m.end_phase("phase_b")
        summary = m.summary()
        self.assertIn("phases", summary)
        self.assertIn("phase_a", summary["phases"])
        self.assertIn("phase_b", summary["phases"])

    def test_end_phase_without_start_returns_zero(self):
        m = self._make_metrics()
        result = m.end_phase("nonexistent")
        self.assertEqual(result, 0.0)
        self.assertNotIn("nonexistent", m.phases)

    def test_total_duration_grows_over_time(self):
        m = self._make_metrics()
        t1 = m.summary()["total_duration_s"]
        time.sleep(0.05)
        t2 = m.summary()["total_duration_s"]
        self.assertGreater(t2, t1)


if __name__ == "__main__":
    unittest.main()
