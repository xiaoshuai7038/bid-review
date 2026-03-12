from __future__ import annotations

import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from app.review.execution_policy import ReviewExecutionPolicy, normalize_review_profile
from app.review.prepared_artifacts import (
    OCRFilterPolicy,
    extract_or_load_word_image_manifest,
    load_or_build_bid_artifact,
    load_or_build_tender_artifact,
)
from app.runtime_paths import default_document_parser_temp_root, ensure_dir

try:
    import pdfplumber

    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    from pypdf import PdfReader

    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

try:
    import docx

    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

mcp = FastMCP(name="document-parser", instructions="项目内置的 PDF 和 Word 文档解析工具。")

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}


def _review_policy() -> ReviewExecutionPolicy:
    profile = normalize_review_profile(os.getenv("BID_REVIEW_REVIEW_PROFILE", "thorough"))
    return ReviewExecutionPolicy.for_profile(profile)


def _read_pdf_text(file_path: str) -> str:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return f"错误：文件不存在 - {path}"
    try:
        if not (HAS_PDFPLUMBER or HAS_PYPDF):
            return "错误：未安装 PDF 解析依赖。"
        artifact = load_or_build_tender_artifact(path).data
    except Exception as exc:  # noqa: BLE001
        return f"解析PDF时出错：{exc}"
    pages: dict[int, list[str]] = {}
    for item in artifact.get("line_index", []):
        page_no = int(item.get("page_no", 0) or 0)
        if page_no <= 0:
            continue
        pages.setdefault(page_no, []).append(str(item.get("text", "") or ""))
    chunks = [f"第{page_no}页:\n" + "\n".join(lines) for page_no, lines in sorted(pages.items()) if lines]
    return "\n\n".join(chunks).strip() or "警告：PDF文件未提取到文本内容"


def _read_word_text(file_path: str) -> str:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return f"错误：文件不存在 - {path}"
    if not HAS_DOCX:
        return "错误：未安装 Word 解析依赖。"
    try:
        artifact = load_or_build_bid_artifact(path).data
    except Exception as exc:  # noqa: BLE001
        return f"解析Word文件时出错：{exc}"
    sections = artifact.get("sections", [])
    if not isinstance(sections, list):
        return "警告：Word文件未提取到文本内容"
    lines: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title", "") or "").strip()
        if title and title != "文档开头":
            lines.append(title)
        for line in section.get("lines", []):
            if not isinstance(line, dict):
                continue
            text = str(line.get("text", "") or "").strip()
            if text:
                lines.append(text)
        lines.append("")
    merged = "\n".join(lines).strip()
    return merged or "警告：Word文件未提取到文本内容"


def _extract_images_from_word_legacy(file_path: str, output_dir: str | None = None) -> dict[str, Any]:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return {"error": f"文件不存在 - {path}"}
    if path.suffix.lower() != ".docx":
        return {"error": "仅支持 .docx 文件"}

    if output_dir:
        out_dir = Path(output_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        managed_root = default_document_parser_temp_root()
        if managed_root is not None:
            try:
                parent = ensure_dir(managed_root)
            except Exception as exc:  # noqa: BLE001
                return {"error": f"创建文档解析临时目录失败: {exc}"}
            out_dir = Path(tempfile.mkdtemp(prefix="word_images_", dir=str(parent))).resolve()
        else:
            out_dir = Path(tempfile.mkdtemp(prefix="word_images_")).resolve()

    images: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            media_files = [
                name
                for name in zf.namelist()
                if name.lower().startswith("word/media/")
                and Path(name).suffix.lower() in _IMAGE_SUFFIXES
            ]
            for index, media_name in enumerate(media_files, start=1):
                safe_name = f"{index:03d}_{Path(media_name).name}"
                output_path = out_dir / safe_name
                with zf.open(media_name) as src, output_path.open("wb") as dst:
                    dst.write(src.read())
                images.append(
                    {
                        "index": index,
                        "source": media_name,
                        "path": str(output_path),
                        "name": safe_name,
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"提取Word图片失败: {exc}"}

    return {
        "image_count": len(images),
        "image_paths": [item["path"] for item in images],
        "images": images,
        "output_dir": str(out_dir),
    }


def _extract_images_from_word(file_path: str, output_dir: str | None = None) -> dict[str, Any]:
    if output_dir:
        return _extract_images_from_word_legacy(file_path, output_dir)
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return {"error": f"文件不存在 - {path}"}
    if path.suffix.lower() != ".docx":
        return {"error": "仅支持 .docx 文件"}
    try:
        policy = _review_policy().ocr_filter_policy
        artifact = extract_or_load_word_image_manifest(path, filter_policy=policy).data
        return {
            "image_count": int(artifact.get("image_count_raw", 0) or 0),
            "image_count_raw": int(artifact.get("image_count_raw", 0) or 0),
            "image_count_unique": int(artifact.get("image_count_unique", 0) or 0),
            "image_count_skipped": int(artifact.get("image_count_skipped", 0) or 0),
            "image_paths": list(artifact.get("image_paths", [])),
            "images": list(artifact.get("images", [])),
            "output_dir": str(artifact.get("output_dir", "")),
            "cache_hit": bool(artifact.get("cache_hit", False)),
            "filter_policy": artifact.get("filter_policy", {}),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"提取Word图片失败: {exc}"}


def _pdf_line_groups(file_path: str) -> list[dict[str, Any]]:
    artifact = load_or_build_tender_artifact(Path(file_path).expanduser().resolve()).data
    pages: dict[int, list[dict[str, Any]]] = {}
    for item in artifact.get("line_index", []):
        page_no = int(item.get("page_no", 0) or 0)
        if page_no <= 0:
            continue
        pages.setdefault(page_no, []).append(item)
    return [{"page_no": page_no, "lines": lines} for page_no, lines in sorted(pages.items())]


def _search_hits(lines: list[dict[str, Any]], query: str, *, max_hits: int, context_lines: int) -> list[dict[str, Any]]:
    lowered = query.strip().lower()
    normalized = "".join(ch for ch in lowered if not ch.isspace())
    hits: list[dict[str, Any]] = []
    for index, item in enumerate(lines):
        text = str(item.get("text", "") or "")
        norm = str(item.get("norm", "") or "")
        if lowered not in text.lower() and normalized not in norm:
            continue
        start = max(0, index - context_lines)
        end = min(len(lines), index + context_lines + 1)
        hits.append(
            {
                "line_no": int(item.get("line_no", 0) or 0),
                "text": text,
                "context": [
                    {"line_no": int(lines[pos].get("line_no", 0) or 0), "text": str(lines[pos].get("text", "") or "")}
                    for pos in range(start, end)
                ],
            }
        )
        if len(hits) >= max_hits:
            break
    return hits


@mcp.tool()
async def get_pdf_outline(file_path: str) -> str:
    artifact = load_or_build_tender_artifact(Path(file_path).expanduser().resolve()).data
    return json.dumps(
        {
            "file_path": str(Path(file_path).expanduser().resolve()),
            "file_hash": artifact.get("file_hash"),
            "cache_hit": artifact.get("cache_hit", False),
            **artifact.get("outline", {}),
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
async def read_pdf_pages(file_path: str, start_page: int, end_page: int) -> str:
    grouped = _pdf_line_groups(file_path)
    chunks: list[dict[str, Any]] = []
    for page in grouped:
        page_no = int(page["page_no"])
        if page_no < start_page or page_no > end_page:
            continue
        chunks.append(
            {
                "page_no": page_no,
                "lines": [
                    {"line_no": int(item.get("line_no", 0) or 0), "text": str(item.get("text", "") or "")}
                    for item in page["lines"]
                ],
            }
        )
    return json.dumps(
        {
            "file_path": str(Path(file_path).expanduser().resolve()),
            "start_page": start_page,
            "end_page": end_page,
            "pages": chunks,
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
async def search_pdf_text(file_path: str, query: str, max_hits: int = 20, context_lines: int = 2) -> str:
    grouped = _pdf_line_groups(file_path)
    hits: list[dict[str, Any]] = []
    for page in grouped:
        page_hits = _search_hits(page["lines"], query, max_hits=max_hits, context_lines=context_lines)
        if not page_hits:
            continue
        hits.append({"page_no": int(page["page_no"]), "hits": page_hits})
        if sum(len(item["hits"]) for item in hits) >= max_hits:
            break
    return json.dumps(
        {
            "file_path": str(Path(file_path).expanduser().resolve()),
            "query": query,
            "hits": hits,
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
async def get_word_outline(file_path: str) -> str:
    artifact = load_or_build_bid_artifact(Path(file_path).expanduser().resolve()).data
    sections = []
    for item in artifact.get("sections", []):
        if not isinstance(item, dict):
            continue
        lines = item.get("lines", [])
        first_line = int(lines[0].get("line_no", 0) or 0) if lines else 0
        last_line = int(lines[-1].get("line_no", 0) or 0) if lines else 0
        sections.append(
            {
                "section_id": item.get("id", ""),
                "title": item.get("title", ""),
                "line_start": first_line,
                "line_end": last_line,
                "line_count": len(lines),
            }
        )
    outline = artifact.get("outline", {})
    return json.dumps(
        {
            "file_path": str(Path(file_path).expanduser().resolve()),
            "file_hash": artifact.get("file_hash"),
            "cache_hit": artifact.get("cache_hit", False),
            "sections": sections,
            "template_sections": outline.get("template_sections", []),
            "docx_image_count": outline.get("docx_image_count", 0),
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
async def read_word_section(file_path: str, section_id: str) -> str:
    artifact = load_or_build_bid_artifact(Path(file_path).expanduser().resolve()).data
    sections = artifact.get("sections", [])
    target = next((item for item in sections if isinstance(item, dict) and str(item.get("id", "")) == str(section_id)), None)
    if not isinstance(target, dict):
        return json.dumps({"error": f"未找到 section_id={section_id}"}, ensure_ascii=False, indent=2)
    return json.dumps(
        {
            "file_path": str(Path(file_path).expanduser().resolve()),
            "section_id": target.get("id", ""),
            "title": target.get("title", ""),
            "lines": [
                {"line_no": int(line.get("line_no", 0) or 0), "text": str(line.get("text", "") or "")}
                for line in target.get("lines", [])
                if isinstance(line, dict)
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
async def search_word_text(file_path: str, query: str, max_hits: int = 20, context_lines: int = 2) -> str:
    artifact = load_or_build_bid_artifact(Path(file_path).expanduser().resolve()).data
    hits: list[dict[str, Any]] = []
    for section in artifact.get("sections", []):
        if not isinstance(section, dict):
            continue
        section_hits = _search_hits(section.get("lines", []), query, max_hits=max_hits, context_lines=context_lines)
        if not section_hits:
            continue
        hits.append(
            {
                "section_id": section.get("id", ""),
                "title": section.get("title", ""),
                "hits": section_hits,
            }
        )
        if sum(len(item["hits"]) for item in hits) >= max_hits:
            break
    return json.dumps(
        {
            "file_path": str(Path(file_path).expanduser().resolve()),
            "query": query,
            "hits": hits,
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
async def read_pdf(file_path: str) -> str:
    return _read_pdf_text(file_path)


@mcp.tool()
async def read_word(file_path: str) -> str:
    return _read_word_text(file_path)


@mcp.tool()
async def extract_images_from_word(file_path: str, output_dir: str = "") -> str:
    result = _extract_images_from_word(file_path, output_dir or None)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def list_formats() -> str:
    return json.dumps(
        {
            "supported_formats": {
                "pdf": HAS_PDFPLUMBER or HAS_PYPDF,
                "docx": HAS_DOCX,
                "word_images_extract": HAS_DOCX,
            },
            "libraries": {
                "pdfplumber": HAS_PDFPLUMBER,
                "pypdf": HAS_PYPDF,
                "python_docx": HAS_DOCX,
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
