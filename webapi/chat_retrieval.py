from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

import pymupdf
from PyPDF2 import PdfReader

from pageindex.utils import _create_async_openai_client

from .models import ChatMessage, NodeCitation, PersistedJob

MAX_CONTEXT_NODES = 6
MAX_CONTEXT_CHARS_PER_NODE = 6000
MAX_CONTEXT_TOTAL_CHARS = 24000


def flatten_tree(structure: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    node_map: Dict[str, Dict[str, Any]] = {}

    def walk(node: Dict[str, Any]) -> None:
        node_id = node.get("node_id")
        if node_id:
            node_map[str(node_id)] = node
        for child in node.get("nodes", []) or []:
            walk(child)

    for root in structure:
        walk(root)
    return node_map


def build_tree_prompt_payload(structure: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keep_fields = {
        "title",
        "node_id",
        "summary",
        "prefix_summary",
        "start_index",
        "end_index",
        "line_num",
        "nodes",
    }

    def clean_node(node: Dict[str, Any]) -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}
        for key, value in node.items():
            if key not in keep_fields:
                continue
            if key == "nodes":
                cleaned[key] = [clean_node(child) for child in value] if value else []
            else:
                cleaned[key] = value
        if not cleaned.get("nodes"):
            cleaned.pop("nodes", None)
        return cleaned

    return [clean_node(node) for node in structure]


def _extract_json_text(raw_text: str) -> str:
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        parts = stripped.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                return candidate
    return stripped


def parse_selection_response(
    raw_text: str,
    valid_node_ids: Iterable[str],
    max_nodes: int = MAX_CONTEXT_NODES,
) -> Tuple[str, List[str]]:
    candidate = _extract_json_text(raw_text)
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("Tree search response must be a JSON object")
    thinking = payload.get("thinking")
    node_list = payload.get("node_list")
    if not isinstance(thinking, str):
        raise ValueError("Tree search response must include string field 'thinking'")
    if not isinstance(node_list, list):
        raise ValueError("Tree search response must include list field 'node_list'")

    allowed = {str(node_id) for node_id in valid_node_ids}
    filtered: List[str] = []
    for item in node_list:
        node_id = str(item)
        if node_id not in allowed:
            continue
        if node_id in filtered:
            continue
        filtered.append(node_id)
        if len(filtered) >= max_nodes:
            break
    return thinking.strip(), filtered


def _message_window(messages: List[ChatMessage], max_turns: int = 8) -> List[ChatMessage]:
    if max_turns <= 0:
        return []
    return messages[-max_turns:]


def _message_role(role: str) -> str:
    if role in {"user", "assistant", "system"}:
        return role
    return "user"


def _job_model(job: PersistedJob) -> str:
    model = job.options.get("model")
    if isinstance(model, str) and model.strip():
        return model
    return "gpt-4.1"


def _chunk_text_delta(chunk: Any) -> str:
    """
    Safely extract streamed text delta from OpenAI/Azure chunk payloads.
    Some providers emit housekeeping chunks with empty `choices`.
    """
    choices = getattr(chunk, "choices", None)
    if not choices:
        return ""
    first = choices[0]
    delta_obj = getattr(first, "delta", None)
    if delta_obj is None:
        return ""
    content = getattr(delta_obj, "content", None)
    if not content:
        return ""
    return str(content)


async def select_nodes(
    *,
    query: str,
    history: List[ChatMessage],
    tree_payload: List[Dict[str, Any]],
    valid_node_ids: Iterable[str],
    model: str,
) -> Tuple[str, List[str]]:
    history_block = [
        {"role": _message_role(msg.role.value if hasattr(msg.role, "value") else str(msg.role)), "content": msg.content}
        for msg in _message_window(history, max_turns=8)
    ]

    prompt = (
        "You are given a user question and a document tree.\n"
        "Each node may include title, node_id, summary, prefix_summary, and page/line bounds.\n"
        "Select nodes likely to contain evidence for answering the question.\n"
        "Return strict JSON only in this shape:\n"
        '{"thinking":"...","node_list":["0001","0002"]}\n'
        "Do not include markdown fences or extra text."
    )

    messages = [{"role": "system", "content": prompt}]
    messages.extend(history_block)
    messages.append(
        {
            "role": "user",
            "content": (
                f"Question:\n{query}\n\n"
                f"Document Tree JSON:\n{json.dumps(tree_payload, ensure_ascii=False)}"
            ),
        }
    )

    async with _create_async_openai_client() as client:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
        )
    content = (response.choices[0].message.content or "").strip()
    return parse_selection_response(content, valid_node_ids)


def _extract_pdf_text(pdf_path: str, start_index: int, end_index: int) -> str:
    # Prefer PyMuPDF for more robust text decoding on PDFs with custom fonts.
    try:
        doc = pymupdf.open(pdf_path)
        total_pages = len(doc)
        if total_pages <= 0:
            return ""
        start = max(1, min(start_index, total_pages))
        end = min(total_pages, end_index)
        if end < start:
            end = start
        snippets: List[str] = []
        for page_idx in range(start - 1, end):
            try:
                snippets.append(doc[page_idx].get_text() or "")
            except Exception:
                continue
        doc.close()
        text = "\n".join(snippets).strip()
        if text:
            return text
    except Exception:
        # Fall back to PyPDF2 if PyMuPDF fails unexpectedly.
        pass

    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    if total_pages <= 0:
        return ""
    start = max(1, min(start_index, total_pages))
    end = min(total_pages, end_index)
    if end < start:
        end = start
    snippets: List[str] = []
    for page_idx in range(start - 1, end):
        try:
            snippets.append(reader.pages[page_idx].extract_text() or "")
        except Exception:
            continue
    return "\n".join(snippets).strip()


def _markdown_bounds(
    node: Dict[str, Any],
    nodes_with_line_num: List[Tuple[int, str]],
    total_lines: int,
) -> Tuple[int, int]:
    start = int(node.get("line_num") or 1)
    end = total_lines
    for candidate_line, _ in nodes_with_line_num:
        if candidate_line > start:
            end = candidate_line - 1
            break
    return max(1, start), max(start, end)


def _extract_markdown_text(
    md_path: str,
    node: Dict[str, Any],
    node_map: Dict[str, Dict[str, Any]],
) -> str:
    lines = Path(md_path).read_text(encoding="utf-8").splitlines()
    nodes_with_line_num = sorted(
        [
            (int(item.get("line_num")), node_id)
            for node_id, item in node_map.items()
            if item.get("line_num") is not None
        ],
        key=lambda item: item[0],
    )
    start, end = _markdown_bounds(node, nodes_with_line_num, len(lines))
    return "\n".join(lines[start - 1 : end]).strip()


def build_citations(
    node_ids: List[str],
    node_map: Dict[str, Dict[str, Any]],
) -> List[NodeCitation]:
    citations: List[NodeCitation] = []
    for node_id in node_ids:
        node = node_map.get(node_id, {})
        citations.append(
            NodeCitation(
                node_id=node_id,
                title=node.get("title"),
                start_index=node.get("start_index"),
                end_index=node.get("end_index"),
                line_num=node.get("line_num"),
            )
        )
    return citations


def get_context_for_nodes(
    *,
    job: PersistedJob,
    node_ids: List[str],
    node_map: Dict[str, Dict[str, Any]],
    max_nodes: int = MAX_CONTEXT_NODES,
    max_chars_per_node: int = MAX_CONTEXT_CHARS_PER_NODE,
    max_chars_total: int = MAX_CONTEXT_TOTAL_CHARS,
) -> List[Dict[str, Any]]:
    context_items: List[Dict[str, Any]] = []
    used_total = 0

    for node_id in node_ids[:max_nodes]:
        node = node_map.get(node_id)
        if not node:
            continue
        text = node.get("text")
        if not isinstance(text, str) or not text.strip():
            if job.input_type == "pdf":
                start = node.get("start_index")
                end = node.get("end_index")
                if isinstance(start, int) and isinstance(end, int):
                    text = _extract_pdf_text(job.input_path, start, end)
            elif job.input_type == "md":
                text = _extract_markdown_text(job.input_path, node, node_map)

        if not isinstance(text, str):
            text = ""
        text = text.strip()
        if not text:
            continue

        clipped = text[:max_chars_per_node]
        remaining = max_chars_total - used_total
        if remaining <= 0:
            break
        clipped = clipped[:remaining]
        if not clipped.strip():
            continue

        used_total += len(clipped)
        context_items.append(
            {
                "node_id": node_id,
                "title": node.get("title"),
                "start_index": node.get("start_index"),
                "end_index": node.get("end_index"),
                "line_num": node.get("line_num"),
                "text": clipped,
            }
        )
    return context_items


def _format_sources_for_prompt(context_nodes: List[Dict[str, Any]]) -> str:
    rows: List[str] = []
    for item in context_nodes:
        source_label = f"node {item['node_id']}"
        if isinstance(item.get("start_index"), int) and isinstance(item.get("end_index"), int):
            source_label += f" (pages {item['start_index']}-{item['end_index']})"
        elif isinstance(item.get("line_num"), int):
            source_label += f" (line {item['line_num']})"
        rows.append(source_label)
    return ", ".join(rows)


async def stream_answer(
    *,
    query: str,
    history: List[ChatMessage],
    context_nodes: List[Dict[str, Any]],
    model: str,
    on_delta: Callable[[str], Awaitable[None]],
) -> str:
    context_blob_parts: List[str] = []
    for item in context_nodes:
        title = item.get("title") or "Untitled"
        page_part = ""
        if isinstance(item.get("start_index"), int) and isinstance(item.get("end_index"), int):
            page_part = f" pages={item['start_index']}-{item['end_index']}"
        elif isinstance(item.get("line_num"), int):
            page_part = f" line={item['line_num']}"
        context_blob_parts.append(
            f"[node_id={item['node_id']}{page_part}] {title}\n{item['text']}"
        )
    context_blob = "\n\n".join(context_blob_parts)
    source_line = _format_sources_for_prompt(context_nodes)

    system_prompt = (
        "Answer the user using only provided context snippets from the indexed document.\n"
        "Use freeform natural language.\n"
        "If evidence is insufficient, state what is missing.\n"
        "Finish with a short 'Sources:' line listing node_ids/pages used."
    )

    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for msg in _message_window(history, max_turns=8):
        messages.append(
            {
                "role": _message_role(msg.role.value if hasattr(msg.role, "value") else str(msg.role)),
                "content": msg.content,
            }
        )
    messages.append(
        {
            "role": "user",
            "content": (
                f"Question:\n{query}\n\n"
                f"Context snippets:\n{context_blob}\n\n"
                f"Candidate sources for citation line: {source_line}"
            ),
        }
    )

    output_parts: List[str] = []
    async with _create_async_openai_client() as client:
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            stream=True,
        )
        async for chunk in stream:
            delta = _chunk_text_delta(chunk)
            if not delta:
                continue
            output_parts.append(delta)
            await on_delta(delta)

    return "".join(output_parts).strip()
