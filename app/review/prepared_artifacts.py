from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from app.review.execution_policy import OCRFilterPolicy
from app.runtime_paths import default_document_parser_temp_root, default_review_cache_root, ensure_dir

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
_SPECIAL_SECTION_TITLES = {
    "投标函",
    "关于行贿等黑名单行为的专项承诺函",
    "开标一览表",
    "分项报价表",
    "法定代表人、主要负责人身份证明",
    "授权委托书",
    "投标保证金交纳证明",
    "基本账户开户许可证或者基本账户证明",
    "资格审查申请书",
    "商务条款偏离表",
    "技术条款偏离表",
    "项目实施团队人员配置",
    "项目设计方案",
    "供货及项目进度安排",
    "售后服务方案",
    "培训方案",
}


@dataclass(slots=True)
class PreparedArtifactBuild:
    data: dict[str, Any]
    cache_hit: bool
    cache_path: Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return " ".join(part for part in text.split())


def _normalize_search_text(text: str) -> str:
    import re

    return re.sub(r"[\s`'\"“”‘’:：;；,，。！？!?\-_/\\|（）()\[\]{}<>]+", "", str(text or "").lower())


def _looks_like_section_heading(text: str) -> bool:
    import re

    stripped = str(text or "").strip()
    if not stripped or len(stripped) > 80:
        return False
    if stripped in _SPECIAL_SECTION_TITLES:
        return True
    if re.match(r"^第[一二三四五六七八九十百0-9]+章", stripped):
        return True
    if re.match(r"^第[一二三四五六七八九十百0-9]+节", stripped):
        return True
    if re.match(r"^[一二三四五六七八九十]+、", stripped):
        return True
    if re.match(r"^\d+(?:\.\d+){0,3}[\.、]?\s*", stripped):
        return True
    return False


def _is_probable_toc_entry(text: str) -> bool:
    import re

    stripped = _clean_text(text)
    if not stripped:
        return False
    if stripped == "目录":
        return True
    if re.match(r"^(?:第[一二三四五六七八九十百0-9]+章|第[一二三四五六七八九十百0-9]+节).+\s+\d+\s*$", stripped):
        return True
    if re.match(r"^(?:\d+(?:\.\d+){0,3}|[一二三四五六七八九十]+)[\.、]?\s*.+\s+\d+\s*$", stripped):
        return True
    return False


def _normalize_outline_title(text: str) -> str:
    import re

    value = _clean_text(text)
    if not value:
        return ""
    value = re.sub(r"\.{2,}\s*\d+\s*$", "", value).strip()
    value = re.sub(r"\s+\d+\s*$", "", value).strip()
    if re.fullmatch(r"\d+", value):
        return ""
    return value


def review_artifact_cache_root() -> Path:
    return ensure_dir(default_review_cache_root())


def _artifact_cache_path(namespace: str, sha: str, file_name: str) -> Path:
    return review_artifact_cache_root() / namespace / sha / file_name


def ocr_backend_fingerprint(backend_url: str) -> str:
    return hashlib.sha256(str(backend_url).strip().encode("utf-8")).hexdigest()[:16]


def ocr_cache_file(image_hash: str, *, language: str, backend_url: str) -> Path:
    fingerprint = ocr_backend_fingerprint(backend_url)
    return _artifact_cache_path("ocr", image_hash, f"{language}-{fingerprint}.json")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_pdf_line_index(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    reader = PdfReader(str(path))
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            continue
        lines = [_clean_text(x) for x in page_text.splitlines()]
        lines = [x for x in lines if x]
        for line_no, line_text in enumerate(lines, start=1):
            out.append(
                {
                    "kind": "pdf",
                    "page_no": page_no,
                    "line_no": line_no,
                    "section": "",
                    "text": line_text,
                    "norm": _normalize_search_text(line_text),
                }
            )
    return out


def _build_pdf_outline(line_index: list[dict[str, Any]]) -> dict[str, Any]:
    total_pages = max((int(item.get("page_no", 0) or 0) for item in line_index), default=0)
    seen: set[str] = set()
    sections: list[dict[str, Any]] = []
    extra_titles = {"投标人须知前附表", "评标办法前附表", "经济投标文件", "技术投标文件", "商务投标文件"}
    for item in line_index:
        text = _normalize_outline_title(str(item.get("text", "") or ""))
        if not text or len(text) > 60:
            continue
        if not (_looks_like_section_heading(text) or text in extra_titles):
            continue
        if text in seen:
            continue
        seen.add(text)
        sections.append({"title": text, "page_no": int(item.get("page_no", 0) or 0)})
    relevant_keywords = (
        "投标人须知",
        "投标文件格式",
        "技术标准",
        "技术要求",
        "评标办法",
        "资格",
        "报价",
        "服务",
        "偏离表",
        "保证金",
        "开标一览表",
        "分项报价表",
        "投标函",
    )
    relevant_seen: set[str] = set()
    relevant_sections: list[str] = []
    for item in line_index:
        text = _normalize_outline_title(str(item.get("text", "") or ""))
        if not text:
            continue
        if not (_looks_like_section_heading(text) or text in extra_titles):
            continue
        if not any(keyword in text for keyword in relevant_keywords):
            continue
        if text in relevant_seen:
            continue
        relevant_seen.add(text)
        relevant_sections.append(text)
    return {
        "total_pages": total_pages,
        "sections": sections[:60],
        "relevant_sections": relevant_sections,
    }


def load_or_build_tender_artifact(path: Path) -> PreparedArtifactBuild:
    sha = file_sha256(path)
    cache_path = _artifact_cache_path("documents", sha, "tender_artifact.json")
    if cache_path.exists():
        data = _read_json(cache_path)
        data["cache_hit"] = True
        return PreparedArtifactBuild(data=data, cache_hit=True, cache_path=cache_path)
    line_index = _build_pdf_line_index(path)
    outline = _build_pdf_outline(line_index)
    data = {
        "kind": "tender",
        "file_path": str(path.resolve()),
        "file_hash": sha,
        "line_index": line_index,
        "outline": outline,
        "cache_hit": False,
    }
    _write_json(cache_path, data)
    return PreparedArtifactBuild(data=data, cache_hit=False, cache_path=cache_path)


def _build_word_line_index(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    current_section = "文档开头"
    section_line_no = 0
    in_toc = False

    def _push_line(raw_text: str) -> None:
        nonlocal current_section, section_line_no, in_toc
        line_text = _clean_text(raw_text)
        if not line_text:
            return
        if line_text == "目录":
            in_toc = True
            return
        if in_toc:
            if _is_probable_toc_entry(line_text):
                return
            in_toc = False
        if _is_probable_toc_entry(line_text):
            return
        if _looks_like_section_heading(line_text):
            current_section = line_text
            section_line_no = 0
        section_line_no += 1
        out.append(
            {
                "kind": "word",
                "page_no": 0,
                "line_no": section_line_no,
                "section": current_section,
                "text": line_text,
                "norm": _normalize_search_text(line_text),
            }
        )

    doc = Document(str(path))
    body = getattr(doc.element, "body", None)
    if body is None:
        return out
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            _push_line(Paragraph(child, doc).text)
            continue
        if not isinstance(child, CT_Tbl):
            continue
        table = Table(child, doc)
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            _push_line(row_text)
    return out


def _count_docx_images(path: Path) -> int:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return sum(
                1
                for name in zf.namelist()
                if name.lower().startswith("word/media/") and Path(name).suffix.lower() in _IMAGE_SUFFIXES
            )
    except Exception:  # noqa: BLE001
        return 0


def _build_word_sections(line_index: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    current_title = ""
    current_lines: list[dict[str, Any]] = []
    for item in line_index:
        section = str(item.get("section", "") or "文档开头")
        if section != current_title:
            if current_lines:
                grouped.append({"id": str(len(grouped) + 1), "title": current_title or "文档开头", "lines": current_lines})
            current_title = section
            current_lines = []
        current_lines.append({"line_no": int(item["line_no"]), "text": item["text"], "norm": item["norm"]})
    if current_lines:
        grouped.append({"id": str(len(grouped) + 1), "title": current_title or "文档开头", "lines": current_lines})
    return grouped


def load_or_build_bid_artifact(path: Path) -> PreparedArtifactBuild:
    sha = file_sha256(path)
    cache_name = "bid_artifact_pdf.json" if path.suffix.lower() == ".pdf" else "bid_artifact_word.json"
    cache_path = _artifact_cache_path("documents", sha, cache_name)
    if cache_path.exists():
        data = _read_json(cache_path)
        data["cache_hit"] = True
        return PreparedArtifactBuild(data=data, cache_hit=True, cache_path=cache_path)

    if path.suffix.lower() == ".pdf":
        line_index = _build_pdf_line_index(path)
        sections = [item["title"] for item in _build_pdf_outline(line_index).get("sections", [])]
        data = {
            "kind": "bid-pdf",
            "file_path": str(path.resolve()),
            "file_hash": sha,
            "line_index": line_index,
            "outline": {"sections": sections[:60], "template_sections": [], "docx_image_count": 0},
            "cache_hit": False,
        }
    else:
        line_index = _build_word_line_index(path)
        sections = _build_word_sections(line_index)
        data = {
            "kind": "bid-docx",
            "file_path": str(path.resolve()),
            "file_hash": sha,
            "line_index": line_index,
            "sections": sections,
            "outline": {
                "sections": [item["title"] for item in sections[:60]],
                "template_sections": [item["title"] for item in sections if item["title"] in _SPECIAL_SECTION_TITLES],
                "docx_image_count": _count_docx_images(path),
            },
            "cache_hit": False,
        }
    _write_json(cache_path, data)
    return PreparedArtifactBuild(data=data, cache_hit=False, cache_path=cache_path)


def _image_sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _image_dimensions(content: bytes) -> tuple[int, int]:
    try:
        from PIL import Image
        from io import BytesIO

        with Image.open(BytesIO(content)) as image:
            return image.size
    except Exception:  # noqa: BLE001
        return (0, 0)


def _manifest_output_dir(doc_hash: str) -> Path:
    managed_root = default_document_parser_temp_root()
    if managed_root is not None:
        base = ensure_dir(managed_root) / doc_hash
        return ensure_dir(base)
    temp_dir = Path(tempfile.mkdtemp(prefix=f"word_images_{doc_hash[:8]}_")).resolve()
    return temp_dir


def extract_or_load_word_image_manifest(path: Path, *, filter_policy: OCRFilterPolicy) -> PreparedArtifactBuild:
    doc_hash = file_sha256(path)
    cache_path = _artifact_cache_path("images", doc_hash, "manifest.json")
    if cache_path.exists():
        data = _read_json(cache_path)
        data["cache_hit"] = True
        return PreparedArtifactBuild(data=data, cache_hit=True, cache_path=cache_path)

    output_dir = _manifest_output_dir(doc_hash)
    raw_images: list[dict[str, Any]] = []
    unique_paths: list[str] = []
    seen_hashes: dict[str, str] = {}
    skipped_images = 0
    with zipfile.ZipFile(path, "r") as zf:
        media_files = [
            name
            for name in zf.namelist()
            if name.lower().startswith("word/media/") and Path(name).suffix.lower() in _IMAGE_SUFFIXES
        ]
        for index, media_name in enumerate(media_files, start=1):
            content = zf.read(media_name)
            image_hash = _image_sha256_bytes(content)
            width, height = _image_dimensions(content)
            skip_reason = ""
            if not content:
                skip_reason = "empty_file"
            elif len(content) < filter_policy.min_image_bytes:
                skip_reason = "below_min_bytes"
            elif min(width, height) and min(width, height) < filter_policy.min_image_edge_px:
                skip_reason = "below_min_edge"

            is_duplicate = filter_policy.dedup_enabled and image_hash in seen_hashes
            master_id = seen_hashes.get(image_hash, "")
            safe_name = f"{index:03d}_{image_hash[:12]}{Path(media_name).suffix.lower()}"
            output_path = output_dir / safe_name
            if not skip_reason and not is_duplicate:
                output_path.write_bytes(content)
                unique_paths.append(str(output_path))
                seen_hashes[image_hash] = safe_name
            elif skip_reason:
                skipped_images += 1

            raw_images.append(
                {
                    "image_id": str(index),
                    "source_name": media_name,
                    "source_path": str(output_path if output_path.exists() else output_dir / safe_name),
                    "sha256": image_hash,
                    "bytes": len(content),
                    "width": width,
                    "height": height,
                    "section_ref": "",
                    "page_hint": 0,
                    "is_duplicate": bool(is_duplicate),
                    "dedup_master_id": master_id,
                    "skip_reason": skip_reason,
                }
            )

    data = {
        "file_path": str(path.resolve()),
        "file_hash": doc_hash,
        "image_count_raw": len(raw_images),
        "image_count_unique": len(unique_paths),
        "image_count_skipped": skipped_images,
        "image_paths": unique_paths,
        "images": raw_images,
        "output_dir": str(output_dir),
        "cache_hit": False,
        "filter_policy": asdict(filter_policy),
    }
    _write_json(cache_path, data)
    return PreparedArtifactBuild(data=data, cache_hit=False, cache_path=cache_path)
