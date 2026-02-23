import unittest

from webapi.models import JobStage
from webapi.progress import STAGE_PROGRESS, stage_from_log_entry, stage_from_text


class ProgressSignalsTest(unittest.TestCase):
    def test_stdout_signal_maps_to_parsing(self):
        self.assertEqual(stage_from_text("Parsing PDF..."), JobStage.PARSING_INPUT)

    def test_log_signal_maps_to_toc(self):
        entry = {"toc_content": "Table of Contents", "page_index_given_in_toc": "yes"}
        self.assertEqual(stage_from_log_entry(entry), JobStage.TOC_ANALYSIS)

    def test_summary_signal_maps_to_summarization(self):
        self.assertEqual(stage_from_text("Generating summaries for each node..."), JobStage.SUMMARIZATION)

    def test_stage_progress_has_all_stages(self):
        for stage in JobStage:
            self.assertIn(stage, STAGE_PROGRESS)


if __name__ == "__main__":
    unittest.main()
