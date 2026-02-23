from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional

from .models import JobStage


STAGE_PROGRESS: Dict[JobStage, float] = {
    JobStage.QUEUED: 0.05,
    JobStage.PARSING_INPUT: 0.20,
    JobStage.TOC_ANALYSIS: 0.35,
    JobStage.INDEX_BUILD: 0.60,
    JobStage.REFINEMENT: 0.75,
    JobStage.SUMMARIZATION: 0.88,
    JobStage.FINALIZING: 0.95,
    JobStage.COMPLETED: 1.00,
}

STAGE_ORDER = [
    JobStage.QUEUED,
    JobStage.PARSING_INPUT,
    JobStage.TOC_ANALYSIS,
    JobStage.INDEX_BUILD,
    JobStage.REFINEMENT,
    JobStage.SUMMARIZATION,
    JobStage.FINALIZING,
    JobStage.COMPLETED,
]

_SIGNAL_RULES = [
    (
        JobStage.FINALIZING,
        (
            "parsing done, saving to file",
            "tree structure saved to",
        ),
    ),
    (
        JobStage.SUMMARIZATION,
        (
            "generating summaries",
            "if_add_node_summary",
            "doc_description",
            "generate_doc_description",
            "generate_node_summary",
        ),
    ),
    (
        JobStage.REFINEMENT,
        (
            "fix_incorrect_toc",
            "large node",
            "fixing ",
            "incorrect_results",
            "maximum fix attempts",
        ),
    ),
    (
        JobStage.INDEX_BUILD,
        (
            "meta_processor",
            "generate_toc",
            "verify_toc",
            "check all items",
            "accuracy:",
            "process_no_toc",
            "process_toc_",
        ),
    ),
    (
        JobStage.TOC_ANALYSIS,
        (
            "find_toc_pages",
            "toc found",
            "toc_content",
            "detect_page_index",
            "toc_transformer",
            "check_toc",
        ),
    ),
    (
        JobStage.PARSING_INPUT,
        (
            "parsing pdf",
            "processing markdown file",
            "extracting nodes from markdown",
            "extracting text content from nodes",
            "building tree from nodes",
        ),
    ),
]


def stage_rank(stage: JobStage) -> int:
    return STAGE_ORDER.index(stage)


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def stage_from_text(text: str) -> Optional[JobStage]:
    lowered = text.lower()
    for stage, keywords in _SIGNAL_RULES:
        if _contains_any(lowered, keywords):
            return stage
    return None


def stage_from_log_entry(entry: Any) -> Optional[JobStage]:
    if isinstance(entry, dict):
        candidates = [
            json.dumps(entry, ensure_ascii=False),
            *[str(v) for v in entry.values()],
            *[str(k) for k in entry.keys()],
        ]
    else:
        candidates = [str(entry)]

    for candidate in candidates:
        stage = stage_from_text(candidate)
        if stage is not None:
            return stage
    return None
