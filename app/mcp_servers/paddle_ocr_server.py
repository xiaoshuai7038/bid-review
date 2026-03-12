from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
import fitz
from mcp.server.fastmcp import FastMCP
from app.review.execution_policy import ReviewExecutionPolicy, normalize_review_profile
from app.review.prepared_artifacts import file_sha256, ocr_cache_file
from app.runtime_paths import default_ocr_temp_root, ensure_dir

DEFAULT_OCR_BACKEND_URL = "https://u372299-h9rw-37d89577.westd.seetacloud.com:8443"
IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
_TEXT_PRIORITY_KEYS = ("text", "content", "value", "markdown", "md", "plain_text")
_INLINE_METADATA_PATTERNS = (
    re.compile(r"(?<!\S)/root(?:/[^\s]+)*(?=\s|$)"),
    re.compile(r"(?<!\S)min/general/[A-Za-z0-9._-]+(?=\s|$)"),
)
_LEADING_METADATA_LINES = {"min", "general", "document"}

mcp = FastMCP(name="paddle-ocr", instructions="项目内置 OCR MCP bridge，调用统一远端 OCR 服务。")


@dataclass(slots=True)
class OCRFileResult:
    source_path: str
    success: bool
    text: str | None
    error: str | None = None
    elapsed_ms: int | None = None
    cache_hit: bool = False


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def _backend_url() -> str:
    return _env_str("OCRMCP_BACKEND_URL", DEFAULT_OCR_BACKEND_URL)


def _api_key() -> str:
    return _env_str("OCRMCP_API_KEY", "")


def _chunk_size() -> int:
    raw = os.getenv("OCRMCP_CHUNK_SIZE", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except Exception:
            pass
    profile = normalize_review_profile(os.getenv("BID_REVIEW_REVIEW_PROFILE", "thorough"))
    return ReviewExecutionPolicy.for_profile(profile).ocr_concurrency.chunk_size


def _timeout_seconds() -> int:
    raw = _env_str("OCRMCP_TIMEOUT_SECONDS", "600").strip()
    try:
        return max(30, int(raw))
    except Exception:
        return 600


def _max_inflight_chunks() -> int:
    raw = _env_str("OCRMCP_MAX_INFLIGHT_CHUNKS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except Exception:
            pass
    profile = normalize_review_profile(os.getenv("BID_REVIEW_REVIEW_PROFILE", "thorough"))
    return ReviewExecutionPolicy.for_profile(profile).ocr_concurrency.max_inflight_chunks


def _headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    api_key = _api_key().strip()
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _cache_enabled() -> bool:
    return _env_str("OCRMCP_CACHE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def _chunked(items: list[Path], size: int) -> list[list[Path]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _cache_entry_for_path(path: Path, *, language: str) -> tuple[str, Path]:
    image_hash = file_sha256(path)
    cache_path = ocr_cache_file(image_hash, language=language, backend_url=_backend_url())
    return image_hash, cache_path


def _load_cached_result(path: Path, *, language: str) -> OCRFileResult | None:
    if not _cache_enabled():
        return None
    _, cache_path = _cache_entry_for_path(path, language=language)
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    text = str(payload.get("ocr_text") or "").strip()
    if not text:
        return None
    return OCRFileResult(
        source_path=str(path),
        success=True,
        text=text,
        error=None,
        elapsed_ms=int(payload.get("elapsed_ms", 0) or 0),
        cache_hit=True,
    )


def _store_cached_result(path: Path, *, language: str, text: str, elapsed_ms: int | None) -> None:
    if not _cache_enabled():
        return
    _, cache_path = _cache_entry_for_path(path, language=language)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "source_path": str(path),
                "ocr_text": text,
                "elapsed_ms": elapsed_ms,
                "language": language,
                "backend_url": _backend_url(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _managed_ocr_temp_dir(prefix: str) -> tempfile.TemporaryDirectory[str]:
    managed_root = default_ocr_temp_root()
    if managed_root is not None:
        parent = ensure_dir(managed_root)
        return tempfile.TemporaryDirectory(prefix=prefix, dir=str(parent))
    return tempfile.TemporaryDirectory(prefix=prefix)


def _managed_ocr_mkdtemp(prefix: str) -> Path:
    managed_root = default_ocr_temp_root()
    if managed_root is not None:
        parent = ensure_dir(managed_root)
        return Path(tempfile.mkdtemp(prefix=prefix, dir=str(parent))).resolve()
    return Path(tempfile.mkdtemp(prefix=prefix)).resolve()


def _expand_local_images(inputs: list[str], recursive: bool = False) -> list[Path]:
    resolved: list[Path] = []
    for raw in inputs:
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Input path does not exist: {path}")
        if path.is_file():
            if path.suffix.lower() in IMAGE_EXTENSIONS:
                resolved.append(path)
            continue
        pattern = "**/*" if recursive else "*"
        for candidate in sorted(path.glob(pattern)):
            if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
                resolved.append(candidate.resolve())

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in resolved:
        if path not in seen:
            deduped.append(path)
            seen.add(path)
    return deduped


def _summarize_results(results: list[OCRFileResult]) -> dict[str, Any]:
    succeeded = sum(1 for item in results if item.success)
    failed = len(results) - succeeded
    return {"total_files": len(results), "succeeded": succeeded, "failed": failed}


def _preview_results(results: list[OCRFileResult], limit: int = 5) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for item in results[:limit]:
        payload = asdict(item)
        text = payload.get("text")
        if isinstance(text, str) and len(text) > 240:
            payload["text"] = text[:240] + "..."
        preview.append(payload)
    return preview


def _ocr_chunk_via_backend(chunk: list[Path], *, language: str) -> list[OCRFileResult]:
    started = time.perf_counter()
    try:
        temp_dir_ctx = _managed_ocr_temp_dir(prefix="ocr_upload_")
    except Exception as exc:  # noqa: BLE001
        return [
            OCRFileResult(
                source_path=str(path),
                success=False,
                text=None,
                error=f"创建 OCR 临时目录失败: {exc}",
            )
            for path in chunk
        ]
    with temp_dir_ctx as _tmp_dir:
        files = []
        handles = []
        try:
            for path in chunk:
                handle = path.open("rb")
                handles.append(handle)
                files.append(("files", (path.name, handle, "application/octet-stream")))
            data = {"client_paths_json": json.dumps([str(path) for path in chunk], ensure_ascii=False)}
            with httpx.Client(timeout=_timeout_seconds(), headers=_headers(), verify=False) as client:
                response = client.post(f"{_backend_url().rstrip('/')}/v1/ocr/images", data=data, files=files)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001
            return [
                OCRFileResult(
                    source_path=str(path),
                    success=False,
                    text=None,
                    error=str(exc),
                )
                for path in chunk
            ]
        finally:
            for handle in handles:
                handle.close()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    out: list[OCRFileResult] = []
    for index, item in enumerate(payload.get("results", [])):
        client_path = chunk[index] if index < len(chunk) else None
        resolved_path = _resolve_result_source_path(item, client_path)
        text = _extract_clean_ocr_text(item.get("text"))
        result = OCRFileResult(
            source_path=resolved_path or str(client_path) if client_path else "",
            success=bool(item.get("success")),
            text=text,
            error=item.get("error"),
            elapsed_ms=item.get("elapsed_ms") or elapsed_ms,
            cache_hit=False,
        )
        if result.success and result.text and client_path is not None:
            _store_cached_result(client_path, language=language, text=result.text, elapsed_ms=result.elapsed_ms)
        out.append(result)
    if len(out) < len(chunk):
        seen_paths = {item.source_path for item in out}
        for path in chunk:
            if str(path) in seen_paths:
                continue
            out.append(
                OCRFileResult(
                    source_path=str(path),
                    success=False,
                    text=None,
                    error="OCR 后端返回结果数量不足",
                    elapsed_ms=elapsed_ms,
                )
            )
    return out


def _sanitize_ocr_text_line(line: str) -> str:
    cleaned = line.strip()
    for pattern in _INLINE_METADATA_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" \t|,:;[](){}<>")
    if not re.search(r"[\w\u4e00-\u9fff]", cleaned):
        return ""
    return cleaned


def _is_leading_metadata_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.lower() in _LEADING_METADATA_LINES:
        return True
    return any(pattern.fullmatch(stripped) for pattern in _INLINE_METADATA_PATTERNS)


def _join_ocr_text_fragments(fragments: list[str]) -> str:
    lines: list[str] = []
    last_line = ""
    for fragment in fragments:
        raw_lines = fragment.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        start_index = 0
        while start_index < len(raw_lines) and _is_leading_metadata_line(raw_lines[start_index]):
            start_index += 1
        for raw_line in raw_lines[start_index:]:
            cleaned_line = _sanitize_ocr_text_line(raw_line)
            if not cleaned_line or cleaned_line == last_line:
                continue
            lines.append(cleaned_line)
            last_line = cleaned_line
    return "\n".join(lines).strip()


def _extract_ocr_text_fragments(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, dict):
        prioritized: list[str] = []
        saw_priority_key = False
        for key in _TEXT_PRIORITY_KEYS:
            if key in payload:
                saw_priority_key = True
                prioritized.extend(_extract_ocr_text_fragments(payload.get(key)))
        if prioritized:
            return prioritized
        if saw_priority_key:
            return []
        fragments: list[str] = []
        for value in payload.values():
            fragments.extend(_extract_ocr_text_fragments(value))
        return fragments
    if isinstance(payload, (list, tuple, set)):
        fragments: list[str] = []
        for item in payload:
            fragments.extend(_extract_ocr_text_fragments(item))
        return fragments
    return []


def _extract_clean_ocr_text(payload: Any) -> str:
    return _join_ocr_text_fragments(_extract_ocr_text_fragments(payload))


def _resolve_result_source_path(result_item: dict[str, Any], client_path: Path | None) -> str:
    client_source = str(result_item.get("client_path") or "").strip()
    if client_source:
        return client_source
    if client_path is not None:
        return str(client_path)
    backend_source = str(result_item.get("source_path") or "").strip()
    if backend_source.startswith("/root/"):
        return ""
    return backend_source


def _batch_ocr_images(paths: list[Path], *, chunk_size: int | None = None, language: str = "ch") -> dict[str, Any]:
    if not paths:
        return {"summary": {"total_files": 0, "succeeded": 0, "failed": 0}, "results": [], "metrics": {}}

    all_results: list[OCRFileResult] = []
    effective_chunk_size = chunk_size or _chunk_size()
    cached_results: dict[str, OCRFileResult] = {}
    uncached_paths: list[Path] = []
    for path in paths:
        cached = _load_cached_result(path, language=language)
        if cached is not None:
            cached_results[str(path)] = cached
        else:
            uncached_paths.append(path)

    remote_batches = _chunked(uncached_paths, effective_chunk_size)
    remote_results_by_path: dict[str, OCRFileResult] = {}
    if remote_batches:
        max_workers = min(max(1, _max_inflight_chunks()), len(remote_batches))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(_ocr_chunk_via_backend, chunk, language=language): chunk
                for chunk in remote_batches
            }
            for future in as_completed(future_map):
                chunk_results = future.result()
                for result in chunk_results:
                    remote_results_by_path[result.source_path] = result

    for path in paths:
        key = str(path)
        result = cached_results.get(key) or remote_results_by_path.get(key)
        if result is None:
            result = OCRFileResult(
                source_path=key,
                success=False,
                text=None,
                error="OCR 结果缺失",
            )
        all_results.append(result)

    return {
        "summary": _summarize_results(all_results),
        "preview": _preview_results(all_results),
        "results": [asdict(item) for item in all_results],
        "metrics": {
            "total_files": len(paths),
            "cache_hit_count": sum(1 for item in all_results if item.cache_hit),
            "remote_batch_count": len(remote_batches),
            "remote_request_file_count": len(uncached_paths),
            "chunk_size": effective_chunk_size,
            "max_inflight_chunks": _max_inflight_chunks(),
        },
    }


def _ocr_text_from_single_result(result_payload: dict[str, Any]) -> str:
    for item in result_payload.get("results", []):
        if item.get("success"):
            text = _extract_clean_ocr_text(item.get("text"))
            if text:
                return text
        error = str(item.get("error") or "").strip()
        if error:
            return f"错误：{error}"
    return "警告：未识别到文本"


def _collect_images_in_dir(dir_path: str) -> list[str]:
    return [str(path) for path in _expand_local_images([dir_path], recursive=False)]


def _ocr_images_in_directory(dir_path: str, language: str = "ch") -> str:
    if not Path(dir_path).is_dir():
        return f"错误：目录不存在 - {dir_path}"
    image_paths = _collect_images_in_dir(dir_path)
    if not image_paths:
        return json.dumps(
            {"image_count": 0, "results": [], "warning": "目录中未找到可识别图片"},
            ensure_ascii=False,
            indent=2,
        )
    payload = _batch_ocr_images([Path(path) for path in image_paths], language=language)
    return json.dumps(
        {
            "image_count": len(image_paths),
            "processed_count": len(payload.get("results", [])),
            "results": payload.get("results", []),
            "summary": payload.get("summary", {}),
            "metrics": payload.get("metrics", {}),
        },
        ensure_ascii=False,
        indent=2,
    )


def _ocr_image_file(file_path: str, language: str = "ch") -> str:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return f"错误：文件不存在 - {path}"
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return f"错误：不支持的图像格式 {path.suffix}"
    payload = _batch_ocr_images([path], language=language)
    return _ocr_text_from_single_result(payload)


def _render_pdf_to_images(file_path: str, temp_dir: Path, dpi: int = 220) -> list[Path]:
    document = fitz.open(file_path)
    try:
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        output_paths: list[Path] = []
        for index in range(len(document)):
            page = document[index]
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            output_path = temp_dir / f"page_{index + 1:04d}.png"
            pix.save(output_path)
            output_paths.append(output_path)
        return output_paths
    finally:
        document.close()


def _ocr_pdf_file(file_path: str, language: str = "ch") -> str:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return f"错误：文件不存在 - {path}"
    if path.suffix.lower() != ".pdf":
        return "错误：文件不是 PDF 格式"

    try:
        temp_dir = _managed_ocr_mkdtemp(prefix="ocr_pdf_pages_")
    except Exception as exc:  # noqa: BLE001
        return f"OCR处理PDF时出错：创建临时目录失败：{exc}"
    try:
        image_paths = _render_pdf_to_images(str(path), temp_dir)
        if not image_paths:
            return "错误：PDF 未生成可识别页面"
        payload = _batch_ocr_images(image_paths, language=language)
        lines: list[str] = []
        for index, item in enumerate(payload.get("results", []), start=1):
            text = _extract_clean_ocr_text(item.get("text"))
            if not text:
                text = str(item.get("error") or "[未识别到文字]")
            lines.append(f"第{index}页（图片OCR）:\n{text}\n")
        return "\n".join(lines).strip() or "警告：未识别到文本"
    except Exception as exc:  # noqa: BLE001
        return f"OCR处理PDF时出错：{exc}"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@mcp.tool()
async def ocr_image(file_path: str, language: str = "ch") -> str:
    return _ocr_image_file(file_path, language)


@mcp.tool()
async def ocr_pdf(file_path: str, language: str = "ch") -> str:
    return _ocr_pdf_file(file_path, language)


@mcp.tool()
async def ocr_images_in_dir(dir_path: str, language: str = "ch") -> str:
    return _ocr_images_in_directory(dir_path, language)


@mcp.tool()
async def ocr_status() -> str:
    with httpx.Client(timeout=15, headers=_headers(), verify=False) as client:
        response = client.get(f"{_backend_url().rstrip('/')}/healthz")
        response.raise_for_status()
        payload = response.json()
    return json.dumps(
        {
            "backend_url": _backend_url(),
            "status": "ok",
            "backend": payload,
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
async def list_languages() -> str:
    return json.dumps({"supported_languages": ["ch", "en"]}, ensure_ascii=False, indent=2)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
