from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
import fitz
from mcp.server.fastmcp import FastMCP

DEFAULT_OCR_BACKEND_URL = "https://u372299-h9rw-37d89577.westd.seetacloud.com:8443"
IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}

mcp = FastMCP(name="paddle-ocr", instructions="项目内置 OCR MCP bridge，调用统一远端 OCR 服务。")


@dataclass(slots=True)
class OCRFileResult:
    source_path: str
    success: bool
    text: str | None
    error: str | None = None
    elapsed_ms: int | None = None


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def _backend_url() -> str:
    return _env_str("OCRMCP_BACKEND_URL", DEFAULT_OCR_BACKEND_URL)


def _api_key() -> str:
    return _env_str("OCRMCP_API_KEY", "")


def _chunk_size() -> int:
    raw = _env_str("OCRMCP_CHUNK_SIZE", "16").strip()
    try:
        return max(1, int(raw))
    except Exception:
        return 16


def _timeout_seconds() -> int:
    raw = _env_str("OCRMCP_TIMEOUT_SECONDS", "600").strip()
    try:
        return max(30, int(raw))
    except Exception:
        return 600


def _headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    api_key = _api_key().strip()
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _chunked(items: list[Path], size: int) -> list[list[Path]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


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


def _batch_ocr_images(paths: list[Path], *, chunk_size: int | None = None) -> dict[str, Any]:
    if not paths:
        return {"summary": {"total_files": 0, "succeeded": 0, "failed": 0}, "results": []}

    all_results: list[OCRFileResult] = []
    effective_chunk_size = chunk_size or _chunk_size()

    with httpx.Client(timeout=_timeout_seconds(), headers=_headers(), verify=False) as client:
        for chunk in _chunked(paths, effective_chunk_size):
            with tempfile.TemporaryDirectory(prefix="ocr_upload_") as _tmp_dir:
                files = []
                handles = []
                try:
                    for path in chunk:
                        handle = path.open("rb")
                        handles.append(handle)
                        files.append(("files", (path.name, handle, "application/octet-stream")))
                    data = {"client_paths_json": json.dumps([str(path) for path in chunk], ensure_ascii=False)}
                    response = client.post(f"{_backend_url().rstrip('/')}/v1/ocr/images", data=data, files=files)
                    response.raise_for_status()
                    payload = response.json()
                finally:
                    for handle in handles:
                        handle.close()

            for item in payload.get("results", []):
                all_results.append(
                    OCRFileResult(
                        source_path=str(item.get("source_path", "")),
                        success=bool(item.get("success")),
                        text=item.get("text"),
                        error=item.get("error"),
                        elapsed_ms=item.get("elapsed_ms"),
                    )
                )

    return {
        "summary": _summarize_results(all_results),
        "preview": _preview_results(all_results),
        "results": [asdict(item) for item in all_results],
    }


def _ocr_text_from_single_result(result_payload: dict[str, Any]) -> str:
    for item in result_payload.get("results", []):
        if item.get("success"):
            text = str(item.get("text") or "").strip()
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
    payload = _batch_ocr_images([Path(path) for path in image_paths])
    return json.dumps(
        {
            "image_count": len(image_paths),
            "processed_count": len(payload.get("results", [])),
            "results": payload.get("results", []),
            "summary": payload.get("summary", {}),
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
    payload = _batch_ocr_images([path])
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

    temp_dir = Path(tempfile.mkdtemp(prefix="ocr_pdf_pages_"))
    try:
        image_paths = _render_pdf_to_images(str(path), temp_dir)
        if not image_paths:
            return "错误：PDF 未生成可识别页面"
        payload = _batch_ocr_images(image_paths)
        lines: list[str] = []
        for index, item in enumerate(payload.get("results", []), start=1):
            text = str(item.get("text") or "").strip()
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
