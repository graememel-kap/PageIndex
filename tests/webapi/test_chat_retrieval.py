import json
import tempfile
import unittest
from pathlib import Path

import pymupdf

from webapi.chat_retrieval import (
    _chunk_text_delta,
    build_tree_prompt_payload,
    flatten_tree,
    get_context_for_nodes,
    _extract_pdf_text,
    parse_selection_response,
)
from webapi.models import JobStage, JobStatus, PersistedJob


def make_job(input_path: str, input_type: str = "pdf") -> PersistedJob:
    return PersistedJob(
        id="job_test",
        filename=Path(input_path).name,
        input_type=input_type,
        status=JobStatus.COMPLETED,
        stage=JobStage.COMPLETED,
        progress=1.0,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        options={"model": "gpt-4.1"},
        input_path=input_path,
        log_file=None,
        result_file=None,
        error=None,
        stdout_tail=[],
        activity=[],
        pid=None,
    )


class ChatRetrievalTest(unittest.TestCase):
    def test_chunk_text_delta_handles_empty_choices(self):
        class Chunk:
            def __init__(self, choices):
                self.choices = choices

        class Delta:
            def __init__(self, content):
                self.content = content

        class Choice:
            def __init__(self, delta):
                self.delta = delta

        self.assertEqual(_chunk_text_delta(Chunk([])), "")
        self.assertEqual(_chunk_text_delta(Chunk([Choice(Delta(None))])), "")
        self.assertEqual(_chunk_text_delta(Chunk([Choice(Delta("hello"))])), "hello")

    def test_flatten_tree_and_payload(self):
        structure = [
            {
                "title": "Root",
                "node_id": "0001",
                "summary": "root summary",
                "text": "root text",
                "nodes": [
                    {
                        "title": "Child",
                        "node_id": "0002",
                        "summary": "child summary",
                        "text": "child text",
                    }
                ],
            }
        ]
        node_map = flatten_tree(structure)
        payload = build_tree_prompt_payload(structure)

        self.assertIn("0001", node_map)
        self.assertIn("0002", node_map)
        self.assertNotIn("text", payload[0])
        self.assertNotIn("text", payload[0]["nodes"][0])

    def test_parse_selection_response(self):
        raw = json.dumps(
            {"thinking": "these sections look relevant", "node_list": ["0002", "9999", "0001"]}
        )
        thinking, node_ids = parse_selection_response(raw, valid_node_ids=["0001", "0002"])

        self.assertEqual(thinking, "these sections look relevant")
        self.assertEqual(node_ids, ["0002", "0001"])

    def test_parse_selection_response_invalid(self):
        with self.assertRaises(Exception):
            parse_selection_response("not json", valid_node_ids=["0001"])

    def test_pdf_context_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "sample.pdf"
            doc = pymupdf.open()
            page1 = doc.new_page()
            page1.insert_text((72, 72), "Page one alpha")
            page2 = doc.new_page()
            page2.insert_text((72, 72), "Page two beta")
            doc.save(pdf_path)
            doc.close()

            job = make_job(str(pdf_path), input_type="pdf")
            node_map = {
                "0001": {
                    "node_id": "0001",
                    "title": "Section A",
                    "start_index": 1,
                    "end_index": 2,
                }
            }

            context = get_context_for_nodes(job=job, node_ids=["0001"], node_map=node_map)
            self.assertEqual(len(context), 1)
            self.assertIn("alpha", context[0]["text"].lower())
            self.assertIn("beta", context[0]["text"].lower())

    def test_pdf_context_extraction_out_of_bounds_range_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "sample.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Single page text")
            doc.save(pdf_path)
            doc.close()

            text = _extract_pdf_text(str(pdf_path), start_index=999, end_index=1200)
            self.assertIsInstance(text, str)


if __name__ == "__main__":
    unittest.main()
