from __future__ import annotations

import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

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


def _read_pdf_text(file_path: str) -> str:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return f"错误：文件不存在 - {path}"

    text = ""
    try:
        if HAS_PDFPLUMBER:
            with pdfplumber.open(path) as pdf:
                for index, page in enumerate(pdf.pages, start=1):
                    page_text = page.extract_text()
                    if page_text:
                        text += f"第{index}页:\n{page_text}\n\n"
        elif HAS_PYPDF:
            with path.open("rb") as handle:
                reader = PdfReader(handle)
                for index, page in enumerate(reader.pages, start=1):
                    page_text = page.extract_text()
                    if page_text:
                        text += f"第{index}页:\n{page_text}\n\n"
        else:
            return "错误：未安装 PDF 解析依赖。"
    except Exception as exc:  # noqa: BLE001
        return f"解析PDF时出错：{exc}"

    return text.strip() or "警告：PDF文件未提取到文本内容"


def _read_word_text(file_path: str) -> str:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return f"错误：文件不存在 - {path}"
    if not HAS_DOCX:
        return "错误：未安装 Word 解析依赖。"

    try:
        document = docx.Document(path)
        lines: list[str] = []
        for para in document.paragraphs:
            text = para.text.strip()
            if text:
                lines.append(text)
        for table in document.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    lines.append(row_text)
            lines.append("")
        merged = "\n".join(lines).strip()
        return merged or "警告：Word文件未提取到文本内容"
    except Exception as exc:  # noqa: BLE001
        return f"解析Word文件时出错：{exc}"


def _extract_images_from_word(file_path: str, output_dir: str | None = None) -> dict[str, Any]:
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return {"error": f"文件不存在 - {path}"}
    if path.suffix.lower() != ".docx":
        return {"error": "仅支持 .docx 文件"}

    out_dir = Path(output_dir).expanduser().resolve() if output_dir else Path(tempfile.mkdtemp(prefix="word_images_"))
    out_dir.mkdir(parents=True, exist_ok=True)

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

