from __future__ import annotations

import json
import re
import os
import time
import zipfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.llm.claude_client import (
    ClaudeCallError,
    ClaudeClient,
    compact_text_for_prompt,
    extract_json_payload,
    prompt_safe_path,
)
from app.llm.prompt_store import render_prompt


_CONTEXT_REQUIREMENT_CATEGORY = "主体一致性"
_CONTEXT_REQUIREMENT_TEXT = (
    "投标文件中的关键主体字段（招标人/采购人/投标人/供应商/开户银行/账户名/账号/"
    "统一社会信用代码/税号/法定代表人/授权代表）必须先建立主体基线，并在全文范围内保持取值一致；"
    "同时必须与所在位置和语义角色一致，不得出现主体错位、字段串用或其他机构信息误填。"
)
_CONTEXT_REQUIREMENT_SOURCE = "系统一致性校验规则（主体基线与位置归属检查）"
_CONTEXT_REQUIREMENT_KEYWORDS = (
    "主体",
    "一致性",
    "基线",
    "全文",
    "错位",
    "不一致",
    "招标人",
    "投标人",
    "采购人",
    "开户银行",
    "账户名",
    "账号",
    "统一社会信用代码",
    "税号",
    "纳税人识别号",
)
_TEMPLATE_REQUIREMENT_RULES: list[dict[str, Any]] = [
    {
        "category": "响应格式",
        "text": "第六章《投标文件格式》列示的经济投标文件、技术投标文件、商务投标文件组成项和必备文书必须完整提交，不得缺项漏项。",
        "source_keywords": [
            ("经济投标文件", "包括但不限于"),
            ("技术投标文件", "包括但不限于"),
            ("商务投标文件", "包括但不限于"),
        ],
        "match_keywords": [
            ("经济投标文件", "技术投标文件", "商务投标文件"),
            ("必备文书", "完整提交"),
        ],
    },
    {
        "category": "响应格式",
        "text": "第六章模板文书中的收件人/抬头字段必须按模板填写对应对象；标注“招标人名称”的应填写招标人，标注“招标代理机构名称”的应填写招标代理机构，不得误填为投标人或其他单位。",
        "source_keywords": [
            ("致", "招标人名称"),
            ("致", "招标代理机构名称"),
        ],
        "match_keywords": [
            ("收件人", "抬头字段"),
            ("招标人名称", "招标代理机构名称"),
        ],
    },
    {
        "category": "响应格式",
        "text": "第六章模板中的项目名称、招标编号等项目标识字段必须与招标文件保持一致，不得错填、漏填或引用其他项目标识。",
        "source_keywords": [
            ("项目名称", "招标编号"),
        ],
        "match_keywords": [
            ("项目名称", "招标编号", "项目标识"),
        ],
    },
    {
        "category": "响应格式",
        "text": "第六章模板中的投标人、法定代表人/主要负责人、委托代理人等主体字段必须按角色准确填写，并在要求位置完成签字或盖章。",
        "source_keywords": [
            ("投标人", "盖公章"),
            ("法定代表人", "委托代理人", "签字或盖章"),
        ],
        "match_keywords": [
            ("投标人", "法定代表人", "委托代理人"),
            ("签字", "盖章", "主体字段"),
        ],
    },
    {
        "category": "响应格式",
        "text": "投标保证金交纳证明、基本账户开户许可证或基本账户证明中的金额、账户主体、账号、开户银行等字段必须按模板和前附表要求完整填写，并与基本账户及投标保证金要求保持一致。",
        "source_keywords": [
            ("投标保证金交纳证明",),
            ("基本账户开户许可证或者基本账户证明",),
            ("投标保证金", "基本账户"),
        ],
        "match_keywords": [
            ("投标保证金", "基本账户"),
            ("开户银行", "账号", "完整填写"),
        ],
    },
    {
        "category": "响应格式",
        "text": "技术条款偏离表、商务条款偏离表必须按模板逐条填写偏离情况，并按要求标注“无偏离”“正偏离”或“负偏离”。",
        "source_keywords": [
            ("技术条款偏离表",),
            ("商务条款偏离表",),
            ("偏离情况", "无偏离"),
        ],
        "match_keywords": [
            ("技术条款偏离表", "商务条款偏离表"),
            ("偏离情况", "无偏离"),
        ],
    },
]
_CONTEXT_FINDING_KEYWORDS = (
    "主体",
    "错位",
    "不一致",
    "冲突",
    "基线",
    "全文",
    "串用",
    "归属",
    "位置",
    "招标人",
    "投标人",
    "采购人",
    "开户银行",
    "账户名",
    "账号",
    "统一社会信用代码",
    "税号",
    "纳税人识别号",
    "法定代表人",
    "授权代表",
    "其他机构",
    "错写",
    "误填",
    "抬头",
    "落款",
)


_IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
}

_CLAUDE_SDK_REVIEW_TOOL_ALLOWLIST = ",".join(
    [
        "document-parser.read_pdf",
        "document-parser.read_word",
        "document-parser.extract_images_from_word",
        "paddle-ocr.ocr_images_in_dir",
        "paddle-ocr.ocr_pdf",
        "Bash",
        "Grep",
        "Glob",
        "TodoWrite",
    ]
)


@contextmanager
def _prefer_claude_sdk_review_tools(client: Any):
    if not isinstance(client, ClaudeClient):
        yield
        return
    original_tools = client.tools
    client.tools = _CLAUDE_SDK_REVIEW_TOOL_ALLOWLIST
    try:
        yield
    finally:
        client.tools = original_tools

_PRECISE_LOCATION_PATTERNS = (
    re.compile(r"第\d+页\s*L\d+(?:-L\d+)?"),
    re.compile(r"《[^》]+》\s*L\d+(?:-L\d+)?"),
    re.compile(r"第[一二三四五六七八九十百0-9]+[章节][^：\n]{0,40}\s*L\d+(?:-L\d+)?"),
    re.compile(r"(?:图片OCR|OCR(?:#\d+)?)\s*L\d+(?:-L\d+)?", flags=re.IGNORECASE),
)

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

_LOCATION_STOPWORDS = {
    "招标文件",
    "投标文件",
    "商务投标文件",
    "经济投标文件",
    "技术投标文件",
    "显示",
    "载明",
    "写明",
    "写为",
    "记载",
    "内容",
    "关键原文",
    "缺少定位信息",
    "请补充章节",
    "请补充页码",
    "请补充段落",
}


def _instruction_requires_ocr(user_instruction: str, extra_instruction: str) -> bool:
    text = f"{user_instruction}\n{extra_instruction}".lower()
    keywords = ["ocr", "图片", "截图", "图像", "扫描", "证据图", "影像"]
    return any(k in text for k in keywords)


def _docx_ocr_required_by_default() -> bool:
    return os.getenv("BID_REVIEW_DOCX_OCR_REQUIRED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _has_ocr_tool_call(tool_calls: list[str]) -> bool:
    for name in tool_calls:
        n = str(name).lower()
        if "paddle-ocr" in n:
            return True
        if "perform_ocr" in n or "perform_pdf_ocr" in n or "perform_batch_ocr" in n:
            return True
    return False


def _has_word_image_extract_call(tool_calls: list[str]) -> bool:
    for name in tool_calls:
        n = str(name).lower()
        if "extract_images_from_word" in n:
            return True
    return False


def _has_word_batch_ocr_call(tool_calls: list[str]) -> bool:
    for name in tool_calls:
        n = str(name).lower()
        if "ocr_images_in_dir" in n:
            return True
        if "perform_batch_ocr" in n:
            return True
    return False


def _append_ocr_enforcement(prompt: str, *, require_word_extract: bool) -> str:
    extra = ""
    if require_word_extract:
        extra = (
            "\n你必须先使用 `document-parser` MCP 服务器中的 Word 图片提取工具"
            "（如 `document-parser.extract_images_from_word` 或 `mcp__document-parser__extract_images_from_word`），"
            "再使用 `paddle-ocr` MCP 服务器中的批量图片 OCR 工具"
            "（如 `paddle-ocr.ocr_images_in_dir` 或 `mcp__paddle-ocr__ocr_images_in_dir`）对提取目录的全部图片完成OCR。"
        )
    enforce = """

[强制执行要求]
你必须至少调用一次 OCR MCP 工具（如 `paddle-ocr.ocr_image` / `paddle-ocr.ocr_pdf`，或 `mcp__paddle-ocr__ocr_image` / `mcp__paddle-ocr__ocr_pdf`）读取图片文字后再输出结果。
如果没有调用 OCR 工具，本次回答视为无效。
"""
    return prompt + enforce + extra


def _append_no_write_enforcement(prompt: str) -> str:
    enforce = """

[只读执行约束]
禁止创建、修改或删除任何本地文件，禁止运行会写文件的 Bash/PowerShell/Python 命令。
只允许使用 MCP 工具读取文档，以及只读命令（ls/find/rg/cat/head/tail）做定位。
若发生任意写操作（含重定向、tee、Out-File、Set-Content、touch、mkdir、mv、cp、rm），本次回答视为无效。
"""
    return prompt + enforce


def _tool_input_to_text(tool_input: Any) -> str:
    if isinstance(tool_input, str):
        return tool_input
    try:
        return json.dumps(tool_input, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return str(tool_input)


_REDIRECT_RE = re.compile(
    r"(?<!\S)(?:\d+)?(?:>>|>|&>)\s*(?P<target>&\d+|\"[^\"]+\"|'[^']+'|[^\s;|&]+)",
    flags=re.IGNORECASE,
)


def _extract_shell_command_text(tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        command = tool_input.get("command")
        if isinstance(command, str):
            return command
    return _tool_input_to_text(tool_input)


def _strip_shell_quotes(token: str) -> str:
    value = token.strip()
    if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
        return value[1:-1]
    return value


def _is_allowed_redirect_target(token: str) -> bool:
    target = _strip_shell_quotes(token).strip().lower().rstrip(";,)")
    if target.startswith("&"):
        # 允许文件描述符重定向，如 2>&1 / >&2。
        return True
    return target in {"/dev/null", "nul", "$null"}


def _has_forbidden_shell_redirection(command: str) -> bool:
    for match in _REDIRECT_RE.finditer(command):
        target = match.group("target")
        if not _is_allowed_redirect_target(target):
            return True
    return False


def _has_forbidden_write_tool_call(tool_uses: list[dict[str, Any]]) -> bool:
    shell_markers = ("bash", "shell", "powershell", "terminal", "command", "exec")
    direct_write_markers = ("write", "edit", "multiedit")
    forbidden_patterns = [
        r"(?<![\w.-])out-file(?![\w.-])",
        r"(?<![\w.-])set-content(?![\w.-])",
        r"(?<![\w.-])add-content(?![\w.-])",
        r"(?<![\w.-])new-item(?![\w.-])",
        r"(?<![\w.-])tee(?![\w.-])",
        r"(?<![\w.-])touch(?![\w.-])",
        r"(?<![\w.-])mkdir(?![\w.-])",
        r"(?<![\w.-])copy-item(?![\w.-])",
        r"(?<![\w.-])move-item(?![\w.-])",
        r"(?<![\w.-])remove-item(?![\w.-])",
        r"(^|[;&|]\s*|\s+)(?:rm|mv|cp)\s+",
        r"(^|[;&|]\s*|\s+)python(?:\.exe)?\s+",
        r"(^|[;&|]\s*|\s+)py\s+-",
        r"(?<![\w.-])uv\s+run\s+python(?![\w.-])",
    ]
    for call in tool_uses:
        name = str(call.get("name", "")).lower()
        if name in direct_write_markers:
            return True
        if name.endswith("__write") or name.endswith("_write") or name.endswith(".write"):
            return True
        if "__write_file" in name or "_write_file" in name or "create_file" in name:
            return True
        if not any(m in name for m in shell_markers):
            continue
        command_text = _extract_shell_command_text(call.get("input")).lower()
        if _has_forbidden_shell_redirection(command_text):
            return True
        if any(re.search(pattern, command_text) for pattern in forbidden_patterns):
            return True
    return False


def _strict_fail_on_forbidden_write() -> bool:
    return os.getenv("BID_REVIEW_FAIL_ON_FORBIDDEN_WRITE", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _local_semantic_guards_enabled() -> bool:
    return os.getenv("BID_REVIEW_ENABLE_LOCAL_SEMANTIC_GUARDS", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _completion_gate_enabled() -> bool:
    return os.getenv("BID_REVIEW_ENFORCE_COMPLETION_GATE", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _iter_tool_input_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_iter_tool_input_strings(v))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            out.extend(_iter_tool_input_strings(item))
    return out


def _to_path_candidate(raw_text: str) -> Path | None:
    text = raw_text.strip().strip("\"'")
    text = text.rstrip(".,;)]}")
    if not text:
        return None
    lower = text.lower()
    if lower.startswith(("http://", "https://", "{env:", "env:")):
        return None
    has_drive = bool(re.match(r"^[a-zA-Z]:[\\/]", text))
    has_sep = "/" in text or "\\" in text
    has_ext = bool(Path(text).suffix)
    if not (has_drive or has_sep or has_ext):
        return None
    path_obj = Path(text).expanduser()
    if not path_obj.is_absolute():
        path_obj = (Path.cwd() / path_obj).resolve(strict=False)
    else:
        path_obj = path_obj.resolve(strict=False)
    return path_obj


def _iter_path_candidates(tool_input: Any) -> list[Path]:
    out: list[Path] = []
    for text in _iter_tool_input_strings(tool_input):
        path_obj = _to_path_candidate(text)
        if path_obj is not None:
            out.append(path_obj)
    return out


def _is_image_file(path_obj: Path) -> bool:
    return path_obj.suffix.lower() in _IMAGE_SUFFIXES


def _canonical_path(path_obj: Path) -> str:
    return str(path_obj.resolve(strict=False)).replace("\\", "/").lower()


def _list_image_files(directory: Path) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    out: list[Path] = []
    try:
        for p in directory.rglob("*"):
            if p.is_file() and _is_image_file(p):
                out.append(p.resolve(strict=False))
    except OSError:
        return []
    return out


def _collect_extracted_images_from_tool_uses(tool_uses: list[dict[str, Any]]) -> set[str]:
    images: set[str] = set()
    for call in tool_uses:
        name = str(call.get("name", "")).lower()
        if "extract_images_from_word" not in name:
            continue
        for path_obj in _iter_path_candidates(call.get("input")):
            if path_obj.suffix.lower() == ".docx":
                continue
            if path_obj.exists() and path_obj.is_file() and _is_image_file(path_obj):
                images.add(_canonical_path(path_obj))
                continue
            if path_obj.exists() and path_obj.is_dir():
                for image in _list_image_files(path_obj):
                    images.add(_canonical_path(image))
    return images


def _collect_ocr_target_images_from_tool_uses(tool_uses: list[dict[str, Any]]) -> set[str]:
    images: set[str] = set()
    for call in tool_uses:
        name = str(call.get("name", "")).lower()
        if "ocr_images_in_dir" not in name and "perform_batch_ocr" not in name:
            continue
        paths = _iter_path_candidates(call.get("input"))
        explicit_images = [p for p in paths if _is_image_file(p)]
        if explicit_images:
            for image in explicit_images:
                images.add(_canonical_path(image))
            continue
        for path_obj in paths:
            if path_obj.exists() and path_obj.is_dir():
                for image in _list_image_files(path_obj):
                    images.add(_canonical_path(image))
    return images


def _count_docx_embedded_images(docx_path: Path) -> int:
    if not docx_path.exists() or not docx_path.is_file():
        return 0
    try:
        with zipfile.ZipFile(docx_path, "r") as zf:
            names = zf.namelist()
    except Exception:  # noqa: BLE001
        return 0
    count = 0
    for name in names:
        lowered = name.lower()
        if not lowered.startswith("word/media/"):
            continue
        suffix = Path(lowered).suffix
        if suffix in _IMAGE_SUFFIXES:
            count += 1
    return count


def _validate_docx_ocr_coverage(tool_uses: list[dict[str, Any]], *, bid_path: Path) -> tuple[bool, str]:
    extracted_images = _collect_extracted_images_from_tool_uses(tool_uses)
    ocr_images = _collect_ocr_target_images_from_tool_uses(tool_uses)

    if extracted_images:
        if not ocr_images:
            return False, "无法统计 OCR 覆盖数量（未识别到 ocr_images_in_dir/perform_batch_ocr 的目标图片）。"
        missing = sorted(extracted_images - ocr_images)
        if missing:
            covered = len(extracted_images) - len(missing)
            sample = ", ".join([Path(x).name for x in missing[:3]])
            return (
                False,
                f"Word提图共{len(extracted_images)}张，OCR覆盖{covered}张，缺少{len(missing)}张（示例: {sample}）。",
            )
        return True, f"Word提图共{len(extracted_images)}张，OCR已全量覆盖。"

    expected_count = _count_docx_embedded_images(bid_path)
    if expected_count <= 0:
        return True, "Word未检测到内嵌图片，跳过图片OCR覆盖校验。"
    if not ocr_images:
        return False, (
            "无法统计 OCR 覆盖数量（未识别到 ocr_images_in_dir/perform_batch_ocr 的目标图片），"
            f"但 Word 内嵌图片共{expected_count}张。"
        )
    if len(ocr_images) < expected_count:
        return (
            False,
            f"Word内嵌图片共{expected_count}张，OCR目标仅识别到{len(ocr_images)}张，存在未覆盖图片。",
        )
    return True, f"Word内嵌图片共{expected_count}张，OCR目标识别到{len(ocr_images)}张，满足全量覆盖。"


def _normalize_requirements(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": item.get("id") or f"R{idx:03d}",
                "category": item.get("category") or "",
                "text": item.get("text") or item.get("requirement_text") or "",
                "source": item.get("source") or item.get("source_location") or "",
            }
        )
    return [x for x in out if x["text"]]


def _normalize_status(raw_status: Any) -> str:
    status_text = str(raw_status or "").strip().lower()
    mapping = {
        "non_compliant": "non_compliant",
        "risk": "risk",
        "needs_manual": "needs_manual",
        "不符合": "non_compliant",
        "风险": "risk",
        "需人工复核": "needs_manual",
        "需要人工复核": "needs_manual",
        "人工复核": "needs_manual",
        "manual": "needs_manual",
    }
    return mapping.get(status_text, "needs_manual")


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"[ \t]+", " ", text)
    # 清理末尾省略号，避免“问题描述...”这种不可执行表述
    text = re.sub(r"(?:\.{3,}|…+)\s*$", "", text)
    return text.strip()


def _clean_issue(value: Any) -> str:
    text = _clean_text(value)
    text = re.sub(r"^检查[:：]\s*", "", text)
    text = text.replace("...", "").replace("…", "").strip()
    text = re.sub(r"由于?时间\s*(不够|不足|有限|来不及)[^。]*[。]?", "", text).strip()
    return text


def _has_coarse_location_hint(text: str) -> bool:
    patterns = [
        r"第[一二三四五六七八九十百0-9]+章",
        r"第[一二三四五六七八九十百0-9]+节",
        r"第?[0-9]+页",
        r"\bP[0-9]+\b",
        r"页码",
        r"段落",
        r"第[一二三四五六七八九十百0-9]+段",
        r"条款",
        r"附件",
        r"截图",
        r"图[一二三四五六七八九十0-9]",
        r"表[一二三四五六七八九十0-9]",
    ]
    return any(re.search(p, text) for p in patterns)


def _has_precise_location_hint(text: str) -> bool:
    return any(p.search(text or "") for p in _PRECISE_LOCATION_PATTERNS)


def _has_location_hint(text: str) -> bool:
    return _has_precise_location_hint(text)


def _normalize_search_text(text: str) -> str:
    return re.sub(r"[\s`'\"“”‘’:：;；,，。！？!?\-_/\\|（）()\[\]{}<>]+", "", str(text or "").lower())


def _looks_like_section_heading(text: str) -> bool:
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


def _normalize_outline_title(text: str) -> str:
    value = _clean_text(text)
    if not value:
        return ""
    value = re.sub(r"\.{2,}\s*\d+\s*$", "", value).strip()
    value = re.sub(r"\s+\d+\s*$", "", value).strip()
    if re.fullmatch(r"\d+", value):
        return ""
    return value


@lru_cache(maxsize=32)
def _build_pdf_line_index(path_str: str) -> list[dict[str, Any]]:
    path = Path(path_str)
    if not path.exists() or path.suffix.lower() != ".pdf":
        return []
    try:
        from pypdf import PdfReader
    except Exception:  # noqa: BLE001
        return []

    out: list[dict[str, Any]] = []
    try:
        reader = PdfReader(str(path))
    except Exception:  # noqa: BLE001
        return []

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


@lru_cache(maxsize=32)
def _build_word_line_index(path_str: str) -> list[dict[str, Any]]:
    path = Path(path_str)
    if not path.exists() or path.suffix.lower() != ".docx":
        return []

    out: list[dict[str, Any]] = []
    current_section = "文档开头"
    section_line_no = 0

    def _push_line(raw_text: str) -> None:
        nonlocal current_section, section_line_no
        line_text = _clean_text(raw_text)
        if not line_text:
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

    try:
        doc = Document(str(path))
    except Exception:  # noqa: BLE001
        return []

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


def _collect_tender_outline(path: Path) -> dict[str, Any]:
    line_index = _build_pdf_line_index(str(path.resolve()))
    if not line_index:
        return {"total_pages": 0, "sections": [], "relevant_sections": []}

    total_pages = max(int(item.get("page_no", 0) or 0) for item in line_index)
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
        if len(sections) >= 40:
            break

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
        is_major_chapter = bool(re.match(r"^第[一二三四五六七八九十百0-9]+章", text))
        is_extra_title = text in extra_titles
        if not (is_major_chapter or is_extra_title):
            continue
        if not any(keyword in text for keyword in relevant_keywords):
            continue
        if text in relevant_seen:
            continue
        relevant_seen.add(text)
        relevant_sections.append(text)
    return {
        "total_pages": total_pages,
        "sections": sections,
        "relevant_sections": relevant_sections,
    }


def _collect_bid_outline(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".docx":
        line_index = _build_word_line_index(str(path.resolve()))
        seen: set[str] = set()
        sections: list[str] = []
        for item in line_index:
            section = _clean_text(str(item.get("section", "") or ""))
            if not section or section in seen:
                continue
            seen.add(section)
            sections.append(section)
        template_sections = [section for section in sections if section in _SPECIAL_SECTION_TITLES]
        return {
            "sections": sections[:40],
            "template_sections": template_sections,
            "docx_image_count": _count_docx_embedded_images(path),
        }

    if path.suffix.lower() == ".pdf":
        line_index = _build_pdf_line_index(str(path.resolve()))
        seen: set[str] = set()
        sections: list[str] = []
        for item in line_index:
            text = _clean_text(str(item.get("text", "") or ""))
            if not text or len(text) > 60:
                continue
            if not _looks_like_section_heading(text):
                continue
            if text in seen:
                continue
            seen.add(text)
            sections.append(text)
        return {
            "sections": sections[:40],
            "template_sections": [],
            "docx_image_count": 0,
        }

    return {"sections": [], "template_sections": [], "docx_image_count": 0}


def _estimate_min_requirement_count(
    *,
    tender_outline: dict[str, Any],
    bid_outline: dict[str, Any],
) -> int:
    relevant_tender = len(list(tender_outline.get("relevant_sections", [])))
    template_sections = len(list(bid_outline.get("template_sections", [])))
    section_count = len(list(bid_outline.get("sections", [])))
    if relevant_tender <= 0 and template_sections <= 0 and section_count <= 0:
        return 0
    estimate = max(6, relevant_tender * 2, template_sections, min(12, section_count // 2))
    return min(20, estimate)


def _format_tender_outline_for_prompt(outline: dict[str, Any]) -> str:
    total_pages = int(outline.get("total_pages", 0) or 0)
    sections = list(outline.get("sections", []))
    if not total_pages and not sections:
        return "- 无法预提取招标文件结构，请自行先完成全文结构盘点后再开始提取 requirements。"
    lines = [f"- 总页数: {total_pages}"]
    if sections:
        lines.append("- 检测到的章节/关键块:")
        for item in sections[:20]:
            title = str(item.get("title", "") or "")
            page_no = int(item.get("page_no", 0) or 0)
            lines.append(f"  - 第{page_no}页: {title}")
    return "\n".join(lines)


def _format_bid_outline_for_prompt(outline: dict[str, Any], *, bid_path: Path) -> str:
    sections = list(outline.get("sections", []))
    template_sections = list(outline.get("template_sections", []))
    image_count = int(outline.get("docx_image_count", 0) or 0)
    if not sections and bid_path.suffix.lower() != ".docx":
        return "- 无法预提取投标文件结构，请自行先完成全文结构盘点后再开始逐条审查。"
    lines: list[str] = []
    if sections:
        lines.append(f"- 检测到的正文/模板块数量: {len(sections)}")
        lines.append("- 按出现顺序的章节/模板块（前40个）:")
        for title in sections[:40]:
            lines.append(f"  - {title}")
    if bid_path.suffix.lower() == ".docx":
        lines.append(f"- docx 内嵌图片数: {image_count}")
        if template_sections:
            lines.append("- 识别到的重点模板块:")
            for title in template_sections[:20]:
                lines.append(f"  - {title}")
    return "\n".join(lines) if lines else "- 无法预提取投标文件结构，请自行先完成全文结构盘点。"


def _extract_review_scope(raw_data: dict[str, Any]) -> dict[str, Any]:
    summary = raw_data.get("summary", {})
    if not isinstance(summary, dict):
        return {}
    review_scope = summary.get("review_scope", {})
    return review_scope if isinstance(review_scope, dict) else {}


def _normalize_scope_section_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _clean_text(str(item or ""))
        if text:
            out.append(text)
    return out


def _count_scope_matches(expected: list[str], observed: list[str]) -> int:
    if not expected or not observed:
        return 0
    observed_norm = [_normalize_search_text(x) for x in observed]
    matched = 0
    for item in expected:
        norm = _normalize_search_text(item)
        if any(norm and (norm in candidate or candidate in norm) for candidate in observed_norm):
            matched += 1
    return matched


def _evaluate_review_completion(
    raw_data: dict[str, Any],
    *,
    tender_outline: dict[str, Any],
    bid_outline: dict[str, Any],
    min_requirement_count: int,
    require_word_extract: bool,
    ocr_required: bool,
) -> list[str]:
    reasons: list[str] = []
    has_expectation = bool(min_requirement_count) or bool(tender_outline.get("total_pages")) or bool(
        bid_outline.get("sections")
    ) or bool(bid_outline.get("docx_image_count"))
    if not has_expectation:
        return reasons
    requirements = _normalize_requirements(raw_data.get("requirements"))
    if min_requirement_count > 0 and len(requirements) < min_requirement_count:
        reasons.append(
            f"硬性要求仅提取到 {len(requirements)} 条，低于完成门槛 {min_requirement_count} 条。"
        )

    review_scope = _extract_review_scope(raw_data)
    if not review_scope:
        reasons.append("缺少 review_scope，无法证明已完成全文结构盘点和全文阅读。")
        return reasons

    if not bool(review_scope.get("completion_check_passed", False)):
        reasons.append("review_scope.completion_check_passed 不是 true。")

    tender_total_pages = int(tender_outline.get("total_pages", 0) or 0)
    tender_pages_seen = int(review_scope.get("tender_total_pages_seen", 0) or 0)
    if tender_total_pages and tender_pages_seen < tender_total_pages:
        reasons.append(f"招标文件页数仅确认到 {tender_pages_seen}/{tender_total_pages} 页。")

    tender_expected_sections = [str(x) for x in tender_outline.get("relevant_sections", [])]
    tender_reviewed_sections = _normalize_scope_section_list(review_scope.get("tender_sections_reviewed"))
    if tender_expected_sections:
        required_matches = min(len(tender_expected_sections), max(3, len(tender_expected_sections) // 2))
        actual_matches = _count_scope_matches(tender_expected_sections, tender_reviewed_sections)
        if actual_matches < required_matches:
            reasons.append(
                f"招标文件关键章节覆盖不足，仅覆盖 {actual_matches}/{len(tender_expected_sections)} 个关键块。"
            )

    bid_expected_sections = [str(x) for x in bid_outline.get("template_sections") or bid_outline.get("sections", [])]
    bid_reviewed_sections = _normalize_scope_section_list(review_scope.get("bid_sections_reviewed"))
    if bid_expected_sections:
        required_matches = min(len(bid_expected_sections), max(4, len(bid_expected_sections) // 2))
        actual_matches = _count_scope_matches(bid_expected_sections, bid_reviewed_sections)
        if actual_matches < required_matches:
            reasons.append(
                f"投标文件正文/模板块覆盖不足，仅覆盖 {actual_matches}/{len(bid_expected_sections)} 个关键块。"
            )

    image_count = int(bid_outline.get("docx_image_count", 0) or 0)
    if require_word_extract and ocr_required and image_count > 0:
        images_seen = int(review_scope.get("docx_image_count_seen", 0) or 0)
        if images_seen < image_count:
            reasons.append(f"docx 图片仅确认到 {images_seen}/{image_count} 张。")
        if not bool(review_scope.get("docx_ocr_completed", False)):
            reasons.append("review_scope.docx_ocr_completed 不是 true。")

    return reasons


def _append_completion_enforcement(
    prompt: str,
    *,
    tender_document_map: str,
    bid_document_map: str,
    min_requirement_count: int,
    reasons: list[str],
) -> str:
    reason_block = "\n".join(f"- {item}" for item in reasons[:8])
    enforce = f"""

[全文阅读完成门槛补充要求]
你上一轮结果未通过完成门槛：
{reason_block}

请重新继续阅读，不要复用上一轮的半成品总结。你必须满足以下条件后才能输出最终 JSON：
1. 先完成招标文件全文结构盘点，并确认总页数与关键章节覆盖。
2. 再完成招标文件硬性要求全文提取；最终 `requirements` 不得少于 {min_requirement_count} 条，除非你已经读完整份文档且文档本身确实明显少于此数量。
3. 再完成投标文件正文结构盘点；若是 docx，必须在全量 OCR 完成后重新回到正文和模板字段继续审查。
4. 对已出现明确字段和值的位置（如 `致：`、`开户银行：`、`项目名称：`、`账号：`），必须先做字段级判断，禁止再输出泛化“需人工核验主体一致性/项目信息一致性”来代替。
5. 你必须在 `summary.review_scope` 中如实返回：
   - `tender_total_pages_seen`
   - `tender_sections_reviewed`
   - `bid_sections_reviewed`
   - `docx_image_count_seen`
   - `docx_ocr_completed`
   - `completion_check_passed`

重新审查时，请以以下结构地图为起点继续完成全文阅读：

[招标文件结构地图]
{tender_document_map}

[投标文件结构地图]
{bid_document_map}
"""
    return prompt + enforce


def _extract_location_tokens(text: str) -> list[str]:
    raw = str(text or "")
    raw = re.sub(r"（缺少定位信息[^）]*）", "", raw)
    raw = re.sub(r"第\d+页", " ", raw)
    raw = re.sub(r"\bP\d+\b", " ", raw)
    raw = re.sub(r"L\d+(?:-L?\d+)?", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"第[一二三四五六七八九十百0-9]+[章节段]", " ", raw)
    raw = raw.replace("图片OCR", " ").replace("OCR", " ")

    candidates: list[str] = []
    candidates.extend(re.findall(r"[“\"]([^”\"]{2,120})[”\"]", raw))
    candidates.extend(re.split(r"[；;，,。:：\n|]+", raw))

    tokens: list[str] = []
    seen: set[str] = set()
    for cand in candidates:
        cand_text = _clean_text(cand)
        if not cand_text:
            continue
        pieces = [cand_text]
        pieces.extend(re.findall(r"[\u4e00-\u9fffA-Za-z0-9（）()%\-]{2,80}", cand_text))
        for piece in pieces:
            token = _clean_text(piece)
            token = re.sub(r"(显示|载明|写明|写为|为空白|空白|为空值|为空|缺失)$", "", token)
            token = token.strip()
            if len(token) < 2:
                continue
            if token in _LOCATION_STOPWORDS:
                continue
            key = _normalize_search_text(token)
            if not key or key in seen:
                continue
            seen.add(key)
            tokens.append(key)
    return sorted(tokens, key=len, reverse=True)


def _extract_section_mentions(text: str, known_sections: list[str]) -> list[str]:
    out: list[str] = []
    for section in known_sections:
        if not section or section == "文档开头":
            continue
        if section in text and section not in out:
            out.append(section)
    return out


def _extract_explicit_page_numbers(text: str) -> list[int]:
    out: list[int] = []
    for match in re.finditer(r"第(\d+)页", text or ""):
        out.append(int(match.group(1)))
    for match in re.finditer(r"\bP(\d+)\b", text or "", flags=re.IGNORECASE):
        out.append(int(match.group(1)))
    return sorted(set(out))


def _resolve_precise_location_label(
    evidence: str,
    *,
    line_index: list[dict[str, Any]],
    doc_label: str,
) -> str:
    if not evidence or not line_index or _has_precise_location_hint(evidence):
        return ""

    tokens = _extract_location_tokens(evidence)
    if not tokens:
        return ""

    known_sections = sorted({str(item.get("section", "")) for item in line_index if item.get("section")})
    section_mentions = _extract_section_mentions(evidence, known_sections)
    explicit_pages = _extract_explicit_page_numbers(evidence)

    scored: list[tuple[int, dict[str, Any]]] = []
    for item in line_index:
        score = 0
        norm = str(item.get("norm", ""))
        for token in tokens:
            if token and token in norm:
                score += len(token) * len(token)
        if score <= 0:
            continue
        if section_mentions and str(item.get("section", "")) in section_mentions:
            score += 200
        if item["kind"] == "pdf" and explicit_pages:
            if int(item["page_no"]) in explicit_pages:
                score += 300
            else:
                continue
        scored.append((score, item))

    if not scored:
        return ""

    max_score = max(score for score, _ in scored)
    cutoff = max(9, int(max_score * 0.6))
    kept = [(score, item) for score, item in scored if score >= cutoff]

    grouped: dict[tuple[str, str | int], dict[str, Any]] = {}
    for score, item in kept:
        if item["kind"] == "pdf":
            key: tuple[str, str | int] = ("pdf", int(item["page_no"]))
        else:
            key = ("word", str(item.get("section", "")) or "文档开头")
        bucket = grouped.setdefault(
            key,
            {
                "score": 0,
                "line_numbers": [],
            },
        )
        bucket["score"] += score
        bucket["line_numbers"].append(int(item["line_no"]))

    best_groups = sorted(grouped.items(), key=lambda kv: kv[1]["score"], reverse=True)[:2]
    labels: list[str] = []
    for (kind, key), payload in best_groups:
        line_numbers = sorted(set(payload["line_numbers"]))
        start_line = line_numbers[0]
        end_line = line_numbers[-1]
        line_part = f"L{start_line}-L{end_line}"
        if kind == "pdf":
            labels.append(f"{doc_label}第{key}页 {line_part}")
        else:
            labels.append(f"{doc_label}《{key}》{line_part}")
    return "；".join(labels)


def _prepend_precise_location(evidence: str, location_label: str) -> str:
    if not evidence or not location_label:
        return evidence
    if evidence.startswith(location_label):
        return evidence
    return f"{location_label}：{evidence}"


def _enrich_report_evidence_locations(
    report: dict[str, Any],
    *,
    tender_path: Path,
    bid_path: Path,
) -> dict[str, Any]:
    findings = report.get("findings", [])
    if not isinstance(findings, list):
        return report

    tender_index = _build_pdf_line_index(str(tender_path.resolve()))
    bid_index: list[dict[str, Any]] = []
    if bid_path.suffix.lower() == ".pdf":
        bid_index = _build_pdf_line_index(str(bid_path.resolve()))
    elif bid_path.suffix.lower() == ".docx":
        bid_index = _build_word_line_index(str(bid_path.resolve()))

    enriched: list[dict[str, Any]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        current = dict(item)
        tender_evidence = str(current.get("tender_evidence", "") or "")
        bid_evidence = str(current.get("bid_evidence", "") or "")
        if tender_evidence and not _has_precise_location_hint(tender_evidence):
            label = _resolve_precise_location_label(
                tender_evidence,
                line_index=tender_index,
                doc_label="招标文件",
            )
            current["tender_evidence"] = _prepend_precise_location(tender_evidence, label)
        if bid_evidence and not _has_precise_location_hint(bid_evidence):
            label = _resolve_precise_location_label(
                bid_evidence,
                line_index=bid_index,
                doc_label="投标文件",
            )
            current["bid_evidence"] = _prepend_precise_location(bid_evidence, label)
        enriched.append(current)

    report["findings"] = enriched
    return report


def _find_precise_location_gaps(
    report: dict[str, Any],
    *,
    bid_path: Path,
) -> list[str]:
    findings = report.get("findings", [])
    if not isinstance(findings, list):
        return []

    gaps: list[str] = []
    for idx, item in enumerate(findings, start=1):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "")).strip()
        if status not in {"non_compliant", "risk", "needs_manual"}:
            continue
        issue = _clean_text(str(item.get("issue", "") or ""))[:70]
        finding_id = str(item.get("id", "") or f"F{idx:03d}")
        tender_evidence = str(item.get("tender_evidence", "") or "")
        bid_evidence = str(item.get("bid_evidence", "") or "")
        if not _has_precise_location_hint(tender_evidence):
            gaps.append(f"{finding_id} 的 tender_evidence 缺少精确定位：{issue}")
        if not _has_precise_location_hint(bid_evidence):
            expected = "章节/小节 + Lm-Ln"
            if bid_path.suffix.lower() == ".pdf":
                expected = "第X页 Lm-Ln"
            gaps.append(f"{finding_id} 的 bid_evidence 缺少精确定位（需要 {expected}）：{issue}")
    return gaps


def _append_precise_location_enforcement(
    prompt: str,
    *,
    bid_path: Path,
    gaps: list[str],
) -> str:
    bid_format = "投标文件第X页 Lm-Ln：关键原文"
    if bid_path.suffix.lower() == ".docx":
        bid_format = "投标文件《章节名》Lm-Ln：关键原文"
    gap_block = "\n".join(f"- {g}" for g in gaps[:8])
    enforce = f"""

[证据精确定位强制要求]
你上一次返回的部分 evidence 仍然只有粗粒度定位。请重新读取原始文档，并严格按以下格式输出：
- 招标文件 PDF 证据：`招标文件第X页 Lm-Ln：关键原文`
- 投标文件证据：`{bid_format}`
- OCR 图片证据：`投标文件第X页图片OCR Lm-Ln：关键原文`；若无法确定页码，则写 `投标文件《章节名》图片OCR Lm-Ln：关键原文`

行号编号规则：
- `read_pdf` 的每个 `第X页:` 块内，按换行从上到下编号为 `L1, L2, ...`
- `read_word` 的每个章节/小节/模板标题块内，按换行编号为 `L1, L2, ...`
- OCR 文本按每个图片或每页 OCR 的换行编号为 `L1, L2, ...`

禁止继续使用以下粗粒度格式：
- `P15`
- `第3页`
- `资格审查申请书P3`
- `第六章`
- `缺少定位信息`

以下 finding 上一次仍缺少精确定位，请重点修正：
{gap_block}
"""
    return prompt + enforce


def _collect_review_guard_state(
    *,
    tool_calls: list[str],
    tool_uses: list[dict[str, Any]],
    ocr_required: bool,
    require_word_extract: bool,
    bid_path: Path,
) -> dict[str, Any]:
    has_ocr = _has_ocr_tool_call(tool_calls)
    has_word_extract = _has_word_image_extract_call(tool_calls) if require_word_extract else True
    has_word_batch_ocr = _has_word_batch_ocr_call(tool_calls) if require_word_extract else True
    word_ocr_coverage_ok = True
    word_ocr_coverage_detail = ""
    if ocr_required and require_word_extract and has_word_extract and has_word_batch_ocr:
        word_ocr_coverage_ok, word_ocr_coverage_detail = _validate_docx_ocr_coverage(
            tool_uses,
            bid_path=bid_path,
        )
    has_forbidden_write = _has_forbidden_write_tool_call(tool_uses)
    missing_requirements: list[str] = []
    if ocr_required and not has_ocr:
        missing_requirements.append("OCR工具调用")
    if ocr_required and require_word_extract and not has_word_extract:
        missing_requirements.append("Word图片提取调用")
    if ocr_required and require_word_extract and not has_word_batch_ocr:
        missing_requirements.append("全量图片批量OCR调用")
    ocr_guard_ok = not ocr_required or (
        not missing_requirements and (not require_word_extract or word_ocr_coverage_ok)
    )
    return {
        "has_ocr": has_ocr,
        "has_word_extract": has_word_extract,
        "has_word_batch_ocr": has_word_batch_ocr,
        "word_ocr_coverage_ok": word_ocr_coverage_ok,
        "word_ocr_coverage_detail": word_ocr_coverage_detail,
        "has_forbidden_write": has_forbidden_write,
        "missing_requirements": missing_requirements,
        "ocr_guard_ok": ocr_guard_ok,
    }


def _describe_review_guard_failures(
    state: dict[str, Any],
    *,
    ocr_required: bool,
    require_word_extract: bool,
) -> list[str]:
    parts: list[str] = []
    missing_requirements = [str(x) for x in state.get("missing_requirements", [])]
    if ocr_required and missing_requirements:
        parts.append(f"缺少必要MCP调用（{', '.join(missing_requirements)}）")
    if (
        ocr_required
        and require_word_extract
        and not bool(state.get("word_ocr_coverage_ok", True))
        and str(state.get("word_ocr_coverage_detail", "")).strip()
    ):
        parts.append(str(state.get("word_ocr_coverage_detail", "")).strip())
    if bool(state.get("has_forbidden_write", False)):
        parts.append("检测到写文件/脚本执行行为")
    return parts


def _clean_recommendation(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return text
    text = re.sub(r"由于?时间\s*(不够|不足|有限|来不及)[^。]*[。]?", "", text).strip()
    # 面向业务人员，避免“OCR”缩写术语
    text = re.sub(r"(?i)ocr验证", "核对截图中的文字内容", text)
    text = re.sub(r"(?i)进行ocr", "进行截图文字内容核对", text)
    text = re.sub(r"(?i)\bocr\b", "截图文字内容核对", text)
    text = text.replace(
        "需对相关截图进行核对截图中的文字内容，确保内容符合要求",
        "请核对截图中的文字内容，并标注对应页码和位置，确保内容符合要求",
    )
    text = text.replace(
        "需提供清晰的截图证据并进行截图文字内容核对",
        "请提供清晰截图，并标注对应页码和位置后核对文字内容",
    )
    return text


def _normalize_findings(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        status = _normalize_status(item.get("status"))
        issue = _clean_issue(item.get("issue") or item.get("summary") or "")
        tender_evidence = _clean_text(item.get("tender_evidence") or "")
        bid_evidence = _clean_text(item.get("bid_evidence") or "")
        bid_evidence = re.sub(r"(?i)需ocr验证内容", "需核对截图中的文字内容", bid_evidence)
        bid_evidence = re.sub(r"(?i)ocr验证", "截图文字内容核对", bid_evidence)
        bid_evidence = re.sub(r"(?i)\bocr\b", "截图文字内容核对", bid_evidence)
        recommendation = _clean_recommendation(item.get("recommendation") or "")

        if not bid_evidence:
            bid_evidence = "未提供投标证据"
            if not recommendation:
                recommendation = "请补充可定位的投标证据后再核对。"

        out.append(
            {
                "id": item.get("id") or f"F{idx:03d}",
                "requirement_id": item.get("requirement_id") or "",
                "status": status,
                "issue": issue,
                "tender_evidence": tender_evidence,
                "bid_evidence": bid_evidence,
                "recommendation": recommendation,
            }
        )
    return [x for x in out if x["issue"]]


def _compact_token_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


def _find_context_requirement_id(requirements: list[dict[str, Any]]) -> str:
    for req in requirements:
        text = _compact_token_text(f"{req.get('category', '')} {req.get('text', '')}")
        if any(k in text for k in _CONTEXT_REQUIREMENT_KEYWORDS):
            rid = str(req.get("id", "")).strip()
            if rid:
                return rid
    return ""


def _ensure_context_consistency_requirement(report: dict[str, Any]) -> dict[str, Any]:
    requirements_raw = report.get("requirements", [])
    requirements = requirements_raw if isinstance(requirements_raw, list) else []
    if _find_context_requirement_id(requirements):
        return report

    requirements.append(
        {
            "id": f"R{len(requirements) + 1:03d}",
            "category": _CONTEXT_REQUIREMENT_CATEGORY,
            "text": _CONTEXT_REQUIREMENT_TEXT,
            "source": _CONTEXT_REQUIREMENT_SOURCE,
        }
    )
    report["requirements"] = requirements
    summary = report.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        report["summary"] = summary
    summary["requirement_count"] = len(requirements)
    return report


def _format_pdf_line_source(item: dict[str, Any]) -> str:
    page_no = int(item.get("page_no", 0) or 0)
    line_no = int(item.get("line_no", 0) or 0)
    text = str(item.get("text", "") or "").strip()
    return f"招标文件第{page_no}页 L{line_no}-L{line_no}：{text}"


def _find_template_section_start_page(line_index: list[dict[str, Any]]) -> int:
    for item in line_index:
        text = str(item.get("text", "") or "")
        if "第六章" in text and "投标文件格式" in text:
            return int(item.get("page_no", 0) or 0)
    return 0


def _requirement_matches_keyword_groups(
    requirements: list[dict[str, Any]],
    keyword_groups: list[tuple[str, ...]],
) -> bool:
    for req in requirements:
        if not isinstance(req, dict):
            continue
        blob = " ".join(
            str(req.get(key, "") or "")
            for key in ("category", "text", "source")
        )
        if _match_text_by_keyword_groups(blob, keyword_groups):
            return True
    return False


def _find_requirement_source_from_tender(
    line_index: list[dict[str, Any]],
    keyword_groups: list[tuple[str, ...]],
    *,
    min_page: int = 0,
) -> str:
    for group in keyword_groups:
        keys = tuple(_normalize_search_text(x) for x in group if x)
        if not keys:
            continue
        for item in line_index:
            if min_page and int(item.get("page_no", 0) or 0) < min_page:
                continue
            norm = str(item.get("norm", "") or "")
            if all(key in norm for key in keys):
                return _format_pdf_line_source(item)
    return ""


def _ensure_template_field_requirements(
    report: dict[str, Any],
    *,
    tender_path: Path,
) -> dict[str, Any]:
    requirements_raw = report.get("requirements", [])
    requirements = requirements_raw if isinstance(requirements_raw, list) else []
    if tender_path.suffix.lower() != ".pdf":
        return report
    tender_index = _build_pdf_line_index(str(tender_path.resolve()))
    if not tender_index:
        return report

    start_page = _find_template_section_start_page(tender_index)
    if start_page <= 0:
        return report

    changed = False
    for rule in _TEMPLATE_REQUIREMENT_RULES:
        match_keywords = list(rule.get("match_keywords", []))
        if _requirement_matches_keyword_groups(requirements, match_keywords):
            continue
        source = _find_requirement_source_from_tender(
            tender_index,
            list(rule.get("source_keywords", [])),
            min_page=start_page,
        )
        if not source:
            continue
        requirements.append(
            {
                "id": f"R{len(requirements) + 1:03d}",
                "category": str(rule.get("category", "响应格式")),
                "text": str(rule.get("text", "")),
                "source": source,
            }
        )
        changed = True

    if not changed:
        return report

    report["requirements"] = requirements
    summary = report.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        report["summary"] = summary
    summary["requirement_count"] = len(requirements)
    return report


def _is_context_consistency_finding(finding: dict[str, Any]) -> bool:
    text = _compact_token_text(
        " ".join(
            str(finding.get(k, "") or "")
            for k in ("issue", "tender_evidence", "bid_evidence", "recommendation")
        )
    )
    return any(k in text for k in _CONTEXT_FINDING_KEYWORDS)


def _bind_findings_to_context_requirement(
    findings: list[dict[str, Any]],
    *,
    valid_req_ids: set[str],
    context_req_id: str,
) -> list[dict[str, Any]]:
    if not context_req_id:
        return findings
    out: list[dict[str, Any]] = []
    for item in findings:
        f = dict(item)
        rid = str(f.get("requirement_id", "")).strip()
        if rid not in valid_req_ids and _is_context_consistency_finding(f):
            f["requirement_id"] = context_req_id
        out.append(f)
    return out


def normalize_review_report(data: dict[str, Any]) -> dict[str, Any]:
    requirements_raw = _normalize_requirements(data.get("requirements"))
    req_id_map: dict[str, str] = {}
    requirements: list[dict[str, Any]] = []
    for idx, req in enumerate(requirements_raw, start=1):
        old_id = req.get("id", "")
        new_id = f"R{idx:03d}"
        req_id_map[old_id] = new_id
        item = dict(req)
        item["id"] = new_id
        requirements.append(item)

    findings = _normalize_findings(data.get("findings"))
    for f in findings:
        rid = f.get("requirement_id", "")
        if rid in req_id_map:
            f["requirement_id"] = req_id_map[rid]
    summary = data.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    summary_out = {
        "requirement_count": int(summary.get("requirement_count", len(requirements))),
        "non_compliant_count": sum(1 for f in findings if f["status"] == "non_compliant"),
        "risk_count": sum(1 for f in findings if f["status"] == "risk"),
        "needs_manual_count": sum(1 for f in findings if f["status"] == "needs_manual"),
        "finding_count": int(summary.get("finding_count", len(findings))),
    }
    summary_out["finding_count"] = len(findings)
    summary_out["requirement_count"] = len(requirements)
    return {
        "requirements": requirements,
        "findings": findings,
        "summary": summary_out,
    }


def _dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, f in enumerate(findings, start=1):
        key = (
            (f.get("requirement_id") or "").strip()
            + "|"
            + (f.get("issue") or "").replace(" ", "").strip()
        )
        if not key or key in seen:
            continue
        seen.add(key)
        item = dict(f)
        item["id"] = f"F{idx:03d}"
        out.append(item)
    return out


_STATUS_RANK = {
    "needs_manual": 0,
    "risk": 1,
    "non_compliant": 2,
}


def _extract_docx_text(path: Path) -> str:
    doc: Any | None = None
    for _ in range(3):
        try:
            doc = Document(str(path))
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    if doc is None:
        # 并发读取下 python-docx 偶发失败时，兜底直读 OOXML 文本。
        try:
            with zipfile.ZipFile(path, "r") as zf:
                xml_bytes = zf.read("word/document.xml")
            root = ET.fromstring(xml_bytes)
            raw_texts = [node.text for node in root.iter() if node.text]
            return "\n".join(t.strip() for t in raw_texts if t and t.strip())
        except Exception:  # noqa: BLE001
            return ""

    lines: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            lines.append(text)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            line = " | ".join([c for c in cells if c])
            if line:
                lines.append(line)
    return "\n".join(lines)


def _find_requirement_id_by_keywords(
    requirements: list[dict[str, Any]],
    keyword_groups: list[tuple[str, ...]],
) -> str:
    if not requirements:
        return ""

    indexed: list[tuple[str, str]] = []
    for req in requirements:
        rid = str(req.get("id", "")).strip()
        if not rid:
            continue
        blob = _compact_token_text(
            f"{req.get('category', '')} {req.get('text', '')} {req.get('source', '')}"
        )
        indexed.append((rid, blob))

    for group in keyword_groups:
        keys = tuple(_compact_token_text(x) for x in group if x)
        if not keys:
            continue
        for rid, blob in indexed:
            if all(k in blob for k in keys):
                return rid
    return ""


def _pick_requirement_id(report: dict[str, Any], candidates: list[str]) -> str:
    requirements = report.get("requirements", [])
    if not isinstance(requirements, list):
        return ""
    valid_ids = [str(r.get("id", "")).strip() for r in requirements if str(r.get("id", "")).strip()]
    for rid in candidates:
        if rid and rid in valid_ids:
            return rid
    return valid_ids[0] if valid_ids else ""


def _extract_tender_party_baselines(tender_path: Path | None) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {"owner": set(), "agency": set()}
    if tender_path is None or tender_path.suffix.lower() != ".pdf":
        return out
    line_index = _build_pdf_line_index(str(tender_path.resolve()))
    if not line_index:
        return out

    label_specs = (
        ("owner", ("招标人", "采购人")),
        ("agency", ("招标代理机构",)),
    )
    for item in line_index:
        compact_line = re.sub(r"\s+", "", str(item.get("text", "") or ""))
        if not compact_line:
            continue
        for key, labels in label_specs:
            for label in labels:
                match = re.search(rf"{re.escape(label)}[:：](.+)", compact_line)
                if not match:
                    continue
                normalized = _compact_token_text(_normalize_semantic_field_value(match.group(1)))
                if len(normalized) >= 4:
                    out[key].add(normalized)
    return out


def _assign_finding_ids(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(findings, start=1):
        if not isinstance(item, dict):
            continue
        current = dict(item)
        current["id"] = f"F{idx:03d}"
        out.append(current)
    return out


def _normalize_semantic_field_value(value: Any) -> str:
    text = str(value or "").strip()
    text = re.split(r"[\r\n]", text, maxsplit=1)[0]
    text = re.sub(r"[（(](?:盖[^）)]*|签[^）)]*|签章[^）)]*|公章[^）)]*)[）)]\s*$", "", text)
    text = re.split(r"(?:联系人|联系电话|地址|电话|邮编|备注)\s*[:：]", text, maxsplit=1)[0]
    text = text.strip("`'\"：:，,。.;； ")
    return re.sub(r"\s+", "", text)


def _extract_labeled_field_entries(text: str, labels: tuple[str, ...]) -> list[dict[str, str]]:
    if not text or not labels:
        return []
    label_group = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    pattern = re.compile(
        rf"(?:^|[|｜])\s*(?P<label>{label_group})\s*[:：]?\s*(?P<value>[^\r\n|｜]{{1,120}})",
        flags=re.IGNORECASE,
    )
    out: list[dict[str, str]] = []
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for match in pattern.finditer(line):
            value = _normalize_semantic_field_value(match.group("value"))
            if len(value) < 2:
                continue
            out.append(
                {
                    "label": str(match.group("label")).strip(),
                    "value": value,
                    "line": line,
                }
            )
    return out


def _looks_like_bank_name(value: str) -> bool:
    compact = _compact_token_text(value)
    keywords = (
        "银行",
        "信用社",
        "信用联社",
        "农商银行",
        "农商行",
        "农村商业银行",
        "村镇银行",
        "支行",
        "分行",
        "营业部",
    )
    return any(keyword in compact for keyword in keywords)


def _looks_like_company_name(value: str, entity_names: set[str] | None = None) -> bool:
    compact = _compact_token_text(value)
    if not compact:
        return False
    entity_names = entity_names or set()
    if compact in entity_names:
        return True
    if _looks_like_bank_name(value):
        return False
    keywords = (
        "有限责任公司",
        "股份有限公司",
        "有限公司",
        "公司",
        "集团",
        "研究院",
        "研究所",
        "中心",
        "事务所",
        "分公司",
        "合作社",
        "协会",
        "基金会",
        "招标",
        "咨询",
        "工程",
        "科技",
        "服务",
        "贸易",
        "建设",
        "实业",
    )
    return any(_compact_token_text(keyword) in compact for keyword in keywords)


def _looks_like_person_name(value: str) -> bool:
    compact = _compact_token_text(value)
    if not compact:
        return False
    if any(ch.isdigit() for ch in compact):
        return False
    if _looks_like_bank_name(value):
        return False
    if _looks_like_company_name(value):
        return False
    candidate = re.sub(r"[·•．.]", "", str(value or "").strip())
    return bool(re.fullmatch(r"[\u4e00-\u9fff]{2,8}", candidate))


def _looks_like_account_number(value: str) -> bool:
    compact = re.sub(r"[\s\-]", "", str(value or "").upper())
    if re.fullmatch(r"\d{8,30}", compact):
        return True
    if re.fullmatch(r"[0-9A-Z]{12,30}", compact) and sum(ch.isdigit() for ch in compact) >= 8:
        return True
    return False


def _looks_like_credit_code(value: str) -> bool:
    compact = re.sub(r"\s+", "", str(value or "").upper())
    return bool(re.fullmatch(r"[0-9A-Z]{18}", compact)) and any(ch.isalpha() for ch in compact)


def _looks_like_tax_identifier(value: str) -> bool:
    compact = re.sub(r"\s+", "", str(value or "").upper())
    if _looks_like_credit_code(compact):
        return True
    if not re.fullmatch(r"[0-9A-Z]{15,20}", compact):
        return False
    if _looks_like_account_number(compact):
        return False
    return any(ch.isalpha() for ch in compact)


def _classify_semantic_field_value(value: str, *, entity_names: set[str]) -> str:
    if _looks_like_bank_name(value):
        return "bank_name"
    if _looks_like_credit_code(value):
        return "credit_code"
    if _looks_like_tax_identifier(value):
        return "tax_id"
    if _looks_like_account_number(value):
        return "account_no"
    if _looks_like_person_name(value):
        return "person_name"
    if _looks_like_company_name(value, entity_names):
        return "company_name"
    return "unknown"


def _match_text_by_keyword_groups(text: str, keyword_groups: list[tuple[str, ...]]) -> bool:
    compact = _compact_token_text(text)
    for group in keyword_groups:
        keys = tuple(_compact_token_text(x) for x in group if x)
        if keys and all(k in compact for k in keys):
            return True
    return False


def _upsert_guard_finding(
    report: dict[str, Any],
    *,
    requirement_id: str,
    status: str,
    issue: str,
    tender_evidence: str,
    bid_evidence: str,
    recommendation: str,
    match_groups: list[tuple[str, ...]],
) -> None:
    findings = report.get("findings", [])
    if not isinstance(findings, list):
        findings = []
        report["findings"] = findings

    for item in findings:
        if not isinstance(item, dict):
            continue
        merged_text = " ".join(
            str(item.get(k, "") or "")
            for k in ("issue", "tender_evidence", "bid_evidence", "recommendation")
        )
        if not _match_text_by_keyword_groups(merged_text, match_groups):
            continue

        old_status = str(item.get("status", "needs_manual")).strip()
        if _STATUS_RANK.get(status, 0) > _STATUS_RANK.get(old_status, 0):
            item["status"] = status
        item["issue"] = issue
        if requirement_id:
            item["requirement_id"] = requirement_id
        if not _has_location_hint(str(item.get("bid_evidence", "") or "")):
            item["bid_evidence"] = bid_evidence
        if not str(item.get("tender_evidence", "") or "").strip():
            item["tender_evidence"] = tender_evidence
        if not str(item.get("recommendation", "") or "").strip():
            item["recommendation"] = recommendation
        return

    findings.append(
        {
            "id": "",
            "requirement_id": requirement_id,
            "status": status,
            "issue": issue,
            "tender_evidence": tender_evidence,
            "bid_evidence": bid_evidence,
            "recommendation": recommendation,
        }
    )


def _refresh_summary(report: dict[str, Any]) -> None:
    findings = report.get("findings", [])
    if not isinstance(findings, list):
        findings = []
        report["findings"] = findings
    requirements = report.get("requirements", [])
    if not isinstance(requirements, list):
        requirements = []
        report["requirements"] = requirements
    summary = report.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        report["summary"] = summary
    summary["non_compliant_count"] = sum(1 for f in findings if str(f.get("status", "")) == "non_compliant")
    summary["risk_count"] = sum(1 for f in findings if str(f.get("status", "")) == "risk")
    summary["needs_manual_count"] = sum(1 for f in findings if str(f.get("status", "")) == "needs_manual")
    summary["finding_count"] = len(findings)
    summary["requirement_count"] = len(requirements)


def _finding_merge_key(finding: dict[str, Any]) -> str:
    requirement_id = str(finding.get("requirement_id", "") or "").strip()
    issue = _compact_token_text(finding.get("issue", ""))
    if not issue:
        return ""
    return f"{requirement_id}|{issue}"


def _location_precision_score(text: str) -> int:
    value = str(text or "").strip()
    if not value:
        return 0
    score = 0
    if _has_precise_location_hint(value):
        score += 100
    elif _has_coarse_location_hint(value):
        score += 10
    score += len(re.findall(r"L\d+(?:-L\d+)?", value, flags=re.IGNORECASE)) * 5
    if "图片OCR" in value:
        score += 3
    if "缺少定位信息" in value:
        score -= 50
    return score


def _pick_better_location_evidence(current_text: str, candidate_text: str) -> str:
    current = str(current_text or "")
    candidate = str(candidate_text or "")
    if not candidate.strip():
        return current
    if not current.strip():
        return candidate
    if _location_precision_score(candidate) > _location_precision_score(current):
        return candidate
    return current


def _merge_precise_location_retry_report(
    report: dict[str, Any],
    retry_report: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    findings = report.get("findings", [])
    retry_findings = retry_report.get("findings", [])
    if not isinstance(findings, list) or not isinstance(retry_findings, list):
        return report, False

    retry_by_key = {
        key: item
        for item in retry_findings
        if isinstance(item, dict) and (key := _finding_merge_key(item))
    }

    changed = False
    merged_findings: list[dict[str, Any]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        current = dict(item)
        retry_item = retry_by_key.get(_finding_merge_key(current))
        if isinstance(retry_item, dict):
            better_tender = _pick_better_location_evidence(
                str(current.get("tender_evidence", "") or ""),
                str(retry_item.get("tender_evidence", "") or ""),
            )
            better_bid = _pick_better_location_evidence(
                str(current.get("bid_evidence", "") or ""),
                str(retry_item.get("bid_evidence", "") or ""),
            )
            if better_tender != str(current.get("tender_evidence", "") or ""):
                current["tender_evidence"] = better_tender
                changed = True
            if better_bid != str(current.get("bid_evidence", "") or ""):
                current["bid_evidence"] = better_bid
                changed = True
        merged_findings.append(current)

    if not changed:
        return report, False

    merged_report = dict(report)
    merged_report["findings"] = _dedupe_findings(merged_findings)
    _refresh_summary(merged_report)
    return merged_report, True


def _extract_year_after_anchor(compact_text: str, anchor: str, window: int) -> str:
    pos = compact_text.find(anchor)
    if pos < 0:
        return ""
    seg = compact_text[pos : pos + window]
    match = re.search(r"(20\d{2})年", seg)
    return match.group(1) if match else ""


_FINDING_THEME_RULES: list[dict[str, Any]] = [
    {
        "key": "subject_mismatch",
        "match_groups": [
            ("投标函", "投标人", "招标人"),
            ("主体", "错位"),
        ],
        "canonical_issue": "投标函落款处投标人名称误写为招标人名称，主体信息错位。",
        "default_status": "non_compliant",
        "req_type": "context",
    },
    {
        "key": "name_typo",
        "match_groups": [
            ("有限责任司",),
            ("封面", "名称", "不完整"),
            ("封面", "缺少", "公"),
        ],
        "canonical_issue": "商务投标文件封面投标人名称缺少“公”字，公司名称不完整。",
        "default_status": "non_compliant",
        "req_type": "context",
    },
    {
        "key": "quote_missing",
        "match_groups": [
            ("开标一览表", "分项报价表", "税率"),
            ("含税", "不含税", "税率", "空"),
            ("报价", "未填写"),
        ],
        "canonical_issue": "开标一览表和分项报价表中的含税价、不含税价及税率字段存在空缺。",
        "default_status": "non_compliant",
        "req_type": "quote",
    },
    {
        "key": "date_conflict",
        "match_groups": [
            ("日期", "不一致"),
            ("编制日期", "投标函"),
            ("开标一览表", "日期"),
        ],
        "canonical_issue": "投标文件关键日期存在不一致，可能影响文件内部一致性与有效性判断。",
        "default_status": "risk",
        "req_type": "format",
    },
    {
        "key": "signature_blank",
        "match_groups": [
            ("签字栏", "空白"),
            ("委托代理人", "签字处", "空白"),
            ("法定代表人", "签字或盖章", "空白"),
        ],
        "canonical_issue": "商务/经济投标文件封面法定代表人或委托代理人签字栏为空白。",
        "default_status": "needs_manual",
        "req_type": "sign",
    },
    {
        "key": "bank_proof",
        "match_groups": [
            ("基本账户", "开户许可证"),
            ("投标保证金", "基本账户"),
            ("基本账户", "证明", "缺失"),
        ],
        "canonical_issue": "基本账户证明与投标保证金转出账户信息不足，需补充核验。",
        "default_status": "needs_manual",
        "req_type": "bank",
    },
    {
        "key": "social_security_manual",
        "match_groups": [
            ("项目负责人", "社保"),
            ("社保证明",),
            ("缴纳", "社保"),
        ],
        "canonical_issue": "项目负责人近一年社保证明需人工核对缴纳主体与时间范围。",
        "default_status": "needs_manual",
        "req_type": "social",
    },
    {
        "key": "audit_manual",
        "match_groups": [
            ("财务审计",),
            ("审计报告",),
            ("第三方审计",),
        ],
        "canonical_issue": "财务审计报告需人工核对审计年度与报告完整性。",
        "default_status": "needs_manual",
        "req_type": "audit",
    },
    {
        "key": "cert_manual",
        "match_groups": [
            ("体系认证",),
            ("iso",),
            ("认证证书",),
        ],
        "canonical_issue": "体系认证证书需人工核对有效期及官网查询结果。",
        "default_status": "needs_manual",
        "req_type": "cert",
    },
    {
        "key": "performance_manual",
        "match_groups": [
            ("类似项目", "业绩"),
            ("业绩", "时间"),
            ("项目业绩",),
        ],
        "canonical_issue": "类似项目业绩材料需人工核对项目范围与时间是否满足招标要求。",
        "default_status": "needs_manual",
        "req_type": "performance",
    },
]


def _theme_match_rule(finding: dict[str, Any]) -> dict[str, Any] | None:
    merged_text = " ".join(
        str(finding.get(k, "") or "")
        for k in ("issue", "tender_evidence", "bid_evidence", "recommendation")
    )
    for rule in _FINDING_THEME_RULES:
        if _match_text_by_keyword_groups(merged_text, rule["match_groups"]):
            return rule
    return None


def _finding_quality_score(item: dict[str, Any]) -> int:
    status = str(item.get("status", "needs_manual")).strip()
    score = _STATUS_RANK.get(status, 0) * 10
    if _has_location_hint(str(item.get("bid_evidence", "") or "")):
        score += 2
    if str(item.get("tender_evidence", "") or "").strip():
        score += 1
    return score


def _should_preserve_non_theme_finding(item: dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("status", "")).strip() != "non_compliant":
        return False
    merged_text = " ".join(
        str(item.get(k, "") or "")
        for k in ("issue", "tender_evidence", "bid_evidence", "recommendation")
    )
    return _match_text_by_keyword_groups(
        merged_text,
        [
            ("字段语义不符",),
            ("收件人", "抬头字段"),
        ],
    )


def _theme_requirement_candidates(report: dict[str, Any]) -> dict[str, str]:
    requirements = report.get("requirements", [])
    if not isinstance(requirements, list):
        requirements = []
    context_req_id = _find_context_requirement_id(requirements)
    format_req_id = _find_requirement_id_by_keywords(
        requirements,
        [("投标文件格式",), ("响应格式",), ("格式",)],
    )
    quote_req_id = _find_requirement_id_by_keywords(
        requirements,
        [("含税", "税率"), ("报价",), ("开标一览表",)],
    )
    sign_req_id = _find_requirement_id_by_keywords(
        requirements,
        [("签字", "盖章"), ("签章",), ("电子印章",)],
    )
    bank_req_id = _find_requirement_id_by_keywords(
        requirements,
        [("投标保证金", "基本账户"), ("基本账户",), ("投标保证金",)],
    )
    social_req_id = _find_requirement_id_by_keywords(
        requirements,
        [("社保",), ("项目负责人", "社保")],
    )
    audit_req_id = _find_requirement_id_by_keywords(
        requirements,
        [("财务", "审计"), ("审计报告",)],
    )
    cert_req_id = _find_requirement_id_by_keywords(
        requirements,
        [("体系认证",), ("iso",)],
    )
    performance_req_id = _find_requirement_id_by_keywords(
        requirements,
        [("业绩",), ("类似项目", "业绩")],
    )
    return {
        "context": _pick_requirement_id(report, [context_req_id, format_req_id, quote_req_id, sign_req_id, bank_req_id]),
        "format": _pick_requirement_id(report, [format_req_id, sign_req_id, context_req_id]),
        "quote": _pick_requirement_id(report, [quote_req_id, format_req_id, context_req_id]),
        "sign": _pick_requirement_id(report, [sign_req_id, format_req_id, context_req_id]),
        "bank": _pick_requirement_id(report, [bank_req_id, quote_req_id, context_req_id]),
        "social": _pick_requirement_id(report, [social_req_id, context_req_id]),
        "audit": _pick_requirement_id(report, [audit_req_id, context_req_id]),
        "cert": _pick_requirement_id(report, [cert_req_id, context_req_id]),
        "performance": _pick_requirement_id(report, [performance_req_id, context_req_id]),
    }


def _stabilize_findings(report: dict[str, Any]) -> dict[str, Any]:
    findings = report.get("findings", [])
    if not isinstance(findings, list):
        return report
    req_ids = _theme_requirement_candidates(report)

    themed_best: dict[str, dict[str, Any]] = {}
    other: list[dict[str, Any]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        rule = _theme_match_rule(item)
        if not rule:
            other.append(dict(item))
            continue
        key = str(rule["key"])
        current = themed_best.get(key)
        candidate = dict(item)
        # 优先更高严重度/更完整证据。
        if current is None or _finding_quality_score(candidate) > _finding_quality_score(current):
            themed_best[key] = candidate

    merged: list[dict[str, Any]] = []
    for rule in _FINDING_THEME_RULES:
        key = str(rule["key"])
        item = themed_best.get(key)
        if not item:
            continue
        expected_status = str(rule["default_status"])
        # 主题项状态固定，避免同义问题在不同运行中出现风险级别漂移。
        item["status"] = expected_status
        item["issue"] = str(rule["canonical_issue"])
        req_type = str(rule["req_type"])
        rid = req_ids.get(req_type, "")
        if rid:
            item["requirement_id"] = rid
        merged.append(item)

    preserved_other = [item for item in other if _should_preserve_non_theme_finding(item)]
    merged.extend(preserved_other)

    keep_non_theme = os.getenv("BID_REVIEW_KEEP_NON_THEME_FINDINGS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if keep_non_theme:
        # 可选：保留非主题项用于人工深挖，默认关闭以确保结果稳定。
        for item in other:
            if item in preserved_other:
                continue
            status = str(item.get("status", "")).strip()
            if status == "non_compliant":
                merged.append(item)
                continue
            if status == "needs_manual" and _has_location_hint(str(item.get("bid_evidence", "") or "")):
                merged.append(item)

    report["findings"] = _dedupe_findings(merged)
    _refresh_summary(report)
    return report


def _apply_docx_stability_guards_from_text(
    report: dict[str, Any],
    docx_text: str,
    *,
    tender_path: Path | None = None,
    force_manual_image_checks: bool = False,
) -> dict[str, Any]:
    def _normalize_labeled_party(value: str) -> str:
        text = str(value or "").strip()
        text = re.split(r"[\r\n]", text, maxsplit=1)[0]
        text = re.sub(r"[（(](?:盖[^）)]*|签[^）)]*|签章[^）)]*)[）)]\s*$", "", text)
        text = re.split(r"(?:联系人|联系电话|地址|电话|邮编)\s*[:：]", text, maxsplit=1)[0]
        text = text.strip("`'\"：:，,。.;； ")
        return re.sub(r"\s+", "", text)

    def _extract_labeled_parties(text: str, labels: tuple[str, ...]) -> set[str]:
        out: set[str] = set()
        label_group = "|".join(re.escape(label) for label in labels)
        pattern = re.compile(
            rf"(?:{label_group})\s*[:：]\s*([^\r\n]{{2,120}})",
            flags=re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            normalized = _normalize_labeled_party(match.group(1))
            if len(normalized) >= 4:
                out.add(normalized)
        return out

    def _normalize_section_title(value: str) -> str:
        text = _clean_text(value)
        text = re.sub(r"^[一二三四五六七八九十]+、\s*", "", text)
        text = re.sub(r"^\d+(?:\.\d+){0,3}[、.．]?\s*", "", text)
        return text.strip()

    def _split_docx_sections(text: str) -> dict[str, str]:
        sections: dict[str, list[str]] = {}
        current_title = ""
        current_lines: list[str] = []
        for raw_line in str(text).splitlines():
            line = _clean_text(raw_line)
            if not line:
                continue
            normalized_title = _normalize_section_title(line)
            is_heading = normalized_title in _SPECIAL_SECTION_TITLES or _looks_like_section_heading(line)
            if is_heading:
                if current_title and current_lines and current_title not in sections:
                    sections[current_title] = list(current_lines)
                current_title = normalized_title
                current_lines = [line]
                continue
            if current_title:
                current_lines.append(line)
        if current_title and current_lines and current_title not in sections:
            sections[current_title] = list(current_lines)
        return {title: "\n".join(lines) for title, lines in sections.items()}

    if not docx_text:
        return report

    original_non_theme_findings = [
        dict(item)
        for item in report.get("findings", [])
        if isinstance(item, dict) and _theme_match_rule(item) is None
    ]

    requirements = report.get("requirements", [])
    if not isinstance(requirements, list):
        requirements = []
        report["requirements"] = requirements
    context_req_id = _find_context_requirement_id(requirements)
    format_req_id = _find_requirement_id_by_keywords(
        requirements,
        [
            ("投标文件格式",),
            ("响应格式",),
            ("格式",),
        ],
    )
    quote_req_id = _find_requirement_id_by_keywords(
        requirements,
        [
            ("含税", "税率"),
            ("报价",),
            ("开标一览表",),
        ],
    )
    sign_req_id = _find_requirement_id_by_keywords(
        requirements,
        [
            ("签字", "盖章"),
            ("签章",),
            ("电子印章",),
        ],
    )
    bank_req_id = _find_requirement_id_by_keywords(
        requirements,
        [
            ("投标保证金", "基本账户"),
            ("基本账户",),
            ("投标保证金",),
        ],
    )
    social_req_id = _find_requirement_id_by_keywords(
        requirements,
        [
            ("社保",),
            ("项目负责人", "社保"),
        ],
    )
    audit_req_id = _find_requirement_id_by_keywords(
        requirements,
        [
            ("财务", "审计"),
            ("审计报告",),
        ],
    )
    cert_req_id = _find_requirement_id_by_keywords(
        requirements,
        [
            ("体系认证",),
            ("iso",),
            ("认证证书",),
        ],
    )
    performance_req_id = _find_requirement_id_by_keywords(
        requirements,
        [
            ("业绩",),
            ("类似项目", "业绩"),
        ],
    )

    context_req_id = _pick_requirement_id(
        report,
        [
            context_req_id,
            format_req_id,
            quote_req_id,
            sign_req_id,
            bank_req_id,
            social_req_id,
            audit_req_id,
            cert_req_id,
            performance_req_id,
        ],
    )
    format_req_id = _pick_requirement_id(report, [format_req_id, sign_req_id, context_req_id])
    quote_req_id = _pick_requirement_id(report, [quote_req_id, format_req_id, context_req_id])
    sign_req_id = _pick_requirement_id(report, [sign_req_id, format_req_id, context_req_id])
    bank_req_id = _pick_requirement_id(report, [bank_req_id, quote_req_id, context_req_id])
    social_req_id = _pick_requirement_id(report, [social_req_id, context_req_id])
    audit_req_id = _pick_requirement_id(report, [audit_req_id, context_req_id])
    cert_req_id = _pick_requirement_id(report, [cert_req_id, context_req_id])
    performance_req_id = _pick_requirement_id(report, [performance_req_id, context_req_id])

    req_map = {
        str(r.get("id", "")).strip(): r
        for r in requirements
        if isinstance(r, dict) and str(r.get("id", "")).strip()
    }

    def tender_evidence_for(rid: str, fallback: str) -> str:
        req = req_map.get(rid, {})
        if not isinstance(req, dict):
            return fallback
        text = str(req.get("text", "")).strip()
        source = str(req.get("source", "")).strip()
        if text and source:
            return f"{text}（{source}）"
        if text:
            return text
        if source:
            return source
        return fallback

    compact = _compact_token_text(docx_text)
    bidder_entity_names = _extract_labeled_parties(
        docx_text,
        ("投标人", "供应商", "申请人", "投标单位", "供应商名称"),
    )
    tender_party_baselines = _extract_tender_party_baselines(tender_path)
    section_blocks = _split_docx_sections(docx_text)

    semantic_specs = [
        {
            "labels": ("开户银行", "开户行", "基本账户开户银行", "银行名称"),
            "expected_kind": "bank_name",
            "expected_desc": "银行机构名称",
            "requirement_id": bank_req_id,
            "fallback_tender": "开户银行字段应填写银行机构名称，并与基本账户信息保持一致。",
            "recommendation": "将{label}更正为开户银行全称或开户支行名称，并同步复核账户名、账号和基本账户证明。",
        },
        {
            "labels": ("账户名", "账户名称", "户名", "基本账户名称"),
            "expected_kind": "account_name",
            "expected_desc": "账户主体名称",
            "requirement_id": bank_req_id,
            "fallback_tender": "账户名字段应填写账户主体名称，并与基本账户信息保持一致。",
            "recommendation": "将{label}更正为账户主体名称，并与营业执照、基本账户证明保持一致。",
        },
        {
            "labels": ("账号", "银行账号", "账户账号", "基本账户账号", "银行账户号"),
            "expected_kind": "account_no",
            "expected_desc": "账号串",
            "requirement_id": bank_req_id,
            "fallback_tender": "账号字段应填写有效账号信息，并与基本账户证明保持一致。",
            "recommendation": "将{label}更正为有效账号，并逐位复核与银行证明、转账凭证一致。",
        },
        {
            "labels": ("法定代表人", "法人代表"),
            "expected_kind": "person_name",
            "expected_desc": "自然人姓名",
            "requirement_id": sign_req_id,
            "fallback_tender": "法定代表人字段应填写自然人姓名，并与授权签署信息保持一致。",
            "recommendation": "将{label}更正为法定代表人姓名，并统一复核授权委托书、签字页和营业执照信息。",
        },
        {
            "labels": ("授权代表", "委托代理人", "授权委托人", "被授权人", "代理人"),
            "expected_kind": "person_name",
            "expected_desc": "自然人姓名",
            "requirement_id": sign_req_id,
            "fallback_tender": "授权代表字段应填写自然人姓名，并与授权委托信息保持一致。",
            "recommendation": "将{label}更正为被授权自然人姓名，并复核授权委托页和签字盖章页信息。",
        },
        {
            "labels": ("统一社会信用代码", "社会信用代码"),
            "expected_kind": "credit_code",
            "expected_desc": "统一社会信用代码格式",
            "requirement_id": context_req_id,
            "fallback_tender": "统一社会信用代码字段应填写合法代码格式，并与主体证照一致。",
            "recommendation": "将{label}更正为营业执照一致的统一社会信用代码，并复核全文主体代码信息。",
        },
        {
            "labels": ("税号", "纳税人识别号"),
            "expected_kind": "tax_id",
            "expected_desc": "税号格式",
            "requirement_id": context_req_id,
            "fallback_tender": "税号字段应填写合法税务识别代码，并与主体税务信息一致。",
            "recommendation": "将{label}更正为有效税务识别代码，并复核报价税务信息与主体证照一致。",
        },
    ]

    observed_desc_map = {
        "bank_name": "银行机构名称",
        "company_name": "单位名称",
        "person_name": "自然人姓名",
        "account_no": "账号格式",
        "credit_code": "统一社会信用代码格式",
        "tax_id": "税号格式",
        "unknown": "普通文本",
    }

    receiver_specs = [
        {
            "section_titles": ("投标函", "资格审查申请书", "关于行贿等黑名单行为的专项承诺函"),
            "expected_names": tender_party_baselines["owner"],
            "expected_desc": "招标人名称",
            "requirement_id": format_req_id,
            "fallback_tender": "第六章模板文书中的收件人/抬头字段应按模板填写招标人名称，不得误填为投标人或其他单位。",
            "recommendation": "将《{section}》中的收件人字段更正为招标人全称，并复核同类模板文书抬头是否一致。",
        },
        {
            "section_titles": ("投标保证金交纳证明",),
            "expected_names": tender_party_baselines["agency"],
            "expected_desc": "招标代理机构名称",
            "requirement_id": bank_req_id,
            "fallback_tender": "投标保证金交纳证明中的收件人字段应按模板填写招标代理机构名称，不得误填为投标人或其他单位。",
            "recommendation": "将《{section}》中的收件人字段更正为招标代理机构全称，并复核保证金证明其余字段。",
        },
    ]

    for spec in receiver_specs:
        expected_names = {str(x) for x in spec["expected_names"] if x}
        if not expected_names:
            continue
        for section_title in spec["section_titles"]:
            section_text = section_blocks.get(section_title, "")
            if not section_text:
                continue
            for entry in _extract_labeled_field_entries(section_text, ("致",)):
                value = entry["value"]
                compact_value = _compact_token_text(value)
                if not compact_value or compact_value in expected_names:
                    continue
                actual_desc = "投标人名称" if compact_value in bidder_entity_names else "其他单位名称"
                requirement_id = _pick_requirement_id(
                    report,
                    [str(spec["requirement_id"]), format_req_id, context_req_id],
                )
                _upsert_guard_finding(
                    report,
                    requirement_id=requirement_id,
                    status="non_compliant",
                    issue=(
                        f"《{section_title}》中的收件人/抬头字段“致”应填写{spec['expected_desc']}，"
                        f"当前填写“{value}”，实际呈现为{actual_desc}，与文书角色不一致。"
                    ),
                    tender_evidence=tender_evidence_for(
                        requirement_id,
                        str(spec["fallback_tender"]),
                    ),
                    bid_evidence=(
                        f"文内字段校验：检测到《{section_title}》中“{entry['line']}”，"
                        f"其收件人字段填写为“{value}”，未与模板要求的{spec['expected_desc']}保持一致。"
                    ),
                    recommendation=str(spec["recommendation"]).format(section=section_title),
                    match_groups=[
                        (section_title, "收件人", "抬头字段"),
                        (section_title, "致", spec["expected_desc"]),
                    ],
                )

    for spec in semantic_specs:
        expected_kind = str(spec["expected_kind"])
        labels = tuple(str(x) for x in spec["labels"])
        for entry in _extract_labeled_field_entries(docx_text, labels):
            label = entry["label"]
            value = entry["value"]
            observed_kind = _classify_semantic_field_value(value, entity_names=bidder_entity_names)
            if expected_kind == "bank_name":
                matches = _looks_like_bank_name(value)
            elif expected_kind == "account_name":
                matches = _looks_like_company_name(value, bidder_entity_names) or _looks_like_person_name(value)
            elif expected_kind == "account_no":
                matches = _looks_like_account_number(value)
            elif expected_kind == "person_name":
                matches = _looks_like_person_name(value)
            elif expected_kind == "credit_code":
                matches = _looks_like_credit_code(value)
            elif expected_kind == "tax_id":
                matches = _looks_like_tax_identifier(value)
            else:
                matches = True
            if matches or observed_kind == "unknown":
                continue

            same_as_bidder = _compact_token_text(value) in bidder_entity_names
            bidder_hint = "，且与投标人主体名称重合" if same_as_bidder else ""
            requirement_id = _pick_requirement_id(report, [str(spec["requirement_id"]), context_req_id, format_req_id])
            issue = (
                f"字段“{label}”应填写{spec['expected_desc']}，当前填写“{value}”，"
                f"实际呈现为{observed_desc_map.get(observed_kind, '普通文本')}，字段语义不符。"
            )
            bid_evidence = (
                f"文内字段校验：检测到“{entry['line']}”，其中“{label}”字段值“{value}”呈现为"
                f"{observed_desc_map.get(observed_kind, '普通文本')}{bidder_hint}。"
            )
            _upsert_guard_finding(
                report,
                requirement_id=requirement_id,
                status="non_compliant",
                issue=issue,
                tender_evidence=tender_evidence_for(
                    requirement_id,
                    str(spec["fallback_tender"]),
                ),
                bid_evidence=bid_evidence,
                recommendation=str(spec["recommendation"]).format(label=label),
                match_groups=[
                    (label, "字段语义不符"),
                    (label, spec["expected_desc"]),
                ],
            )

    # 1) 投标函落款主体错位（明确不符合）
    tender_party_names = _extract_labeled_parties(docx_text, ("招标人", "采购人"))
    bid_letter_party_names = _extract_labeled_parties(
        re.search(r"投标函[\s\S]{0,2600}", docx_text).group(0) if re.search(r"投标函[\s\S]{0,2600}", docx_text) else "",
        ("投标人",),
    )
    if tender_party_names and any(name in tender_party_names for name in bid_letter_party_names):
        _upsert_guard_finding(
            report,
            requirement_id=context_req_id,
            status="non_compliant",
            issue="投标函落款处投标人名称误写为招标人名称，主体信息错位。",
            tender_evidence=tender_evidence_for(
                context_req_id,
                "投标文件关键主体名词必须与所在位置和语义角色一致。",
            ),
            bid_evidence="投标函落款页：检测到“投标人”字段值与文内“招标人/采购人”字段值一致，主体不一致。",
            recommendation="将投标函落款处投标人名称更正为投标人法定全称，并复核同页签章信息。",
            match_groups=[
                ("投标函", "投标人", "招标人"),
                ("投标函", "落款", "主体"),
            ],
        )

    # 2) 商务投标文件封面公司名称缺字（明确不符合）
    if "有限责任司" in docx_text:
        _upsert_guard_finding(
            report,
            requirement_id=context_req_id,
            status="non_compliant",
            issue="商务投标文件封面投标人名称缺少“公”字，公司名称不完整。",
            tender_evidence=tender_evidence_for(
                context_req_id,
                "投标文件关键主体名词必须与所在位置和语义角色一致。",
            ),
            bid_evidence="商务投标文件封面：检测到 `有限责任司` 异常，公司名称疑似缺少“公”字。",
            recommendation="将封面公司名称更正为营业执照一致的法定全称，并统一检查全文件主体名称。",
            match_groups=[
                ("有限责任司",),
                ("商务投标文件", "公司名称", "不完整"),
            ],
        )

    # 3) 开标/分项报价关键字段空缺（明确不符合）
    if re.search(r"开标一览表.{0,5000}小写[:：]元", compact) and re.search(r"税率[:：]%", compact):
        _upsert_guard_finding(
            report,
            requirement_id=quote_req_id,
            status="non_compliant",
            issue="开标一览表和分项报价表中的含税价、不含税价及税率字段存在空缺。",
            tender_evidence=tender_evidence_for(
                quote_req_id,
                "投标报价应按招标文件要求完整填报含税、不含税及税率信息。",
            ),
            bid_evidence="开标一览表/分项报价表：`小写： 元`、`税率： %` 等字段为空，无法形成有效报价。",
            recommendation="补齐含税价、不含税价、税率及增值税税额，并校验总价与分项汇总一致。",
            match_groups=[
                ("开标一览表", "含税", "税率"),
                ("分项报价表", "未填写"),
                ("报价", "空缺"),
            ],
        )

    # 4) 关键日期冲突（风险）
    years: dict[str, str] = {}
    raw_patterns = [
        (r"商务投标文件[\s\S]{0,260}?编制日期[:：]\s*(20\d{2})\s*年", "商务封面"),
        (r"经济投标文件[\s\S]{0,260}?编制日期[:：]\s*(20\d{2})\s*年", "经济封面"),
        (r"开标一览表[\s\S]{0,2600}?日\s*期\s*[:：]\s*(20\d{2})\s*年", "开标一览表"),
        (r"投标函[\s\S]{0,2600}?日\s*期\s*[:：]\s*(20\d{2})\s*年", "投标函"),
    ]
    for pattern, key in raw_patterns:
        match = re.search(pattern, docx_text)
        if match:
            years[key] = match.group(1)
    distinct_years = sorted(set(years.values()))
    if len(distinct_years) >= 2:
        details = "、".join([f"{k}{v}年" for k, v in years.items()])
        _upsert_guard_finding(
            report,
            requirement_id=format_req_id,
            status="risk",
            issue="投标文件关键日期存在不一致，可能影响文件内部一致性与有效性判断。",
            tender_evidence=tender_evidence_for(
                format_req_id,
                "投标文件应按格式完整、准确填写关键信息。",
            ),
            bid_evidence=f"日期交叉核对：{details}；存在多个年份并存的情况。",
            recommendation="统一封面、投标函、开标一览表等关键日期，并按投标时点复核全文件时间一致性。",
            match_groups=[
                ("日期", "不一致"),
                ("编制日期", "投标函"),
                ("开标一览表", "年份"),
            ],
        )

    # 5) 封面签字位置空白（需人工复核）
    blank_sign_count = len(re.findall(r"法定代表人、负责人或委托代理人[:：]（签字或盖章）", compact))
    if blank_sign_count >= 1 and "签字或盖章" in compact:
        _upsert_guard_finding(
            report,
            requirement_id=sign_req_id,
            status="needs_manual",
            issue="商务/经济投标文件封面法定代表人或委托代理人签字栏为空白。",
            tender_evidence=tender_evidence_for(
                sign_req_id,
                "投标文件中要求签字或盖章的，应按要求执行。",
            ),
            bid_evidence="商务投标文件封面、经济投标文件封面均出现`法定代表人、负责人或委托代理人：（签字或盖章）`空白栏。",
            recommendation="核对电子签章或手签扫描是否已按要求补齐，并确保封面签署信息完整。",
            match_groups=[
                ("签字栏", "空白"),
                ("法定代表人", "委托代理人", "签字或盖章"),
            ],
        )

    # 6) 基本账户与保证金转出核验项
    if force_manual_image_checks or ("基本账户" in compact and "投标保证金" in compact):
        _upsert_guard_finding(
            report,
            requirement_id=bank_req_id,
            status="needs_manual",
            issue="基本账户证明与投标保证金转出账户信息不足，需补充核验。",
            tender_evidence=tender_evidence_for(
                bank_req_id,
                "投标保证金应由投标人基本账户转出并提供可核验证明。",
            ),
            bid_evidence="投标文件“投标保证金交纳证明/基本账户证明”为图片证据，需核对付款账号与基本账户一致性。",
            recommendation="补充银行转账回单及基本账户证明关键页，并标注账户名、账号、开户行信息。",
            match_groups=[
                ("基本账户", "投标保证金"),
                ("基本账户", "开户许可证"),
                ("投标保证金", "转出账户"),
            ],
        )

    # 7) 关键图片证据人工核验项（固定输出，降低多次运行漂移）
    if force_manual_image_checks or ("社保" in compact):
        _upsert_guard_finding(
            report,
            requirement_id=social_req_id,
            status="needs_manual",
            issue="项目负责人近一年社保证明需人工核对缴纳主体与时间范围。",
            tender_evidence=tender_evidence_for(
                social_req_id,
                "项目负责人相关社保材料需满足招标资格要求。",
            ),
            bid_evidence="投标文件“项目负责人社保证明”为图片证据，需核对缴纳单位、姓名及连续缴纳期间。",
            recommendation="补充清晰社保证明页面，并标注项目负责人姓名、缴纳单位及起止时间。",
            match_groups=[
                ("项目负责人", "社保"),
                ("社保证明",),
            ],
        )

    if force_manual_image_checks or "财务审计报告" in compact or ("审计报告" in compact and "财务" in compact):
        _upsert_guard_finding(
            report,
            requirement_id=audit_req_id,
            status="needs_manual",
            issue="财务审计报告需人工核对审计年度与报告完整性。",
            tender_evidence=tender_evidence_for(
                audit_req_id,
                "财务审计材料应满足招标文件对审计年度和完整性的要求。",
            ),
            bid_evidence="投标文件“财务审计报告”为图片证据，需核对是否为2024年度且包含完整审计正文与签章页。",
            recommendation="补充完整财务审计报告关键页并标注审计年度、审计机构及签章信息。",
            match_groups=[
                ("财务审计",),
                ("审计报告",),
            ],
        )

    if force_manual_image_checks or "体系认证证书" in compact or "iso9001" in compact or "iso27001" in compact or "iso20000" in compact:
        _upsert_guard_finding(
            report,
            requirement_id=cert_req_id,
            status="needs_manual",
            issue="体系认证证书需人工核对有效期及官网查询结果。",
            tender_evidence=tender_evidence_for(
                cert_req_id,
                "体系认证证书需满足有效期与认证范围要求。",
            ),
            bid_evidence="投标文件“体系认证证书”主要为截图证据，需核对证书编号、有效期及官网查询一致性。",
            recommendation="提供清晰证书页和官网查询页，并对照标注证书编号与有效期。",
            match_groups=[
                ("体系认证",),
                ("iso",),
                ("认证证书",),
            ],
        )

    if force_manual_image_checks or "类似项目业绩" in compact or ("项目业绩" in compact and "业绩表" in compact):
        _upsert_guard_finding(
            report,
            requirement_id=performance_req_id,
            status="needs_manual",
            issue="类似项目业绩材料需人工核对项目范围与时间是否满足招标要求。",
            tender_evidence=tender_evidence_for(
                performance_req_id,
                "类似项目业绩应满足招标文件规定的范围和时间要求。",
            ),
            bid_evidence="投标文件“类似项目业绩材料”为合同/发票截图，需核对项目内容、签订时间与招标范围匹配性。",
            recommendation="补充可读性高的业绩证明关键页，并标注项目名称、签订时间和服务内容。",
            match_groups=[
                ("类似项目", "业绩"),
                ("项目业绩",),
            ],
        )

    report["findings"] = _dedupe_findings(report.get("findings", []))
    _refresh_summary(report)
    report = _stabilize_findings(report)
    if original_non_theme_findings:
        report["findings"] = _dedupe_findings(report.get("findings", []) + original_non_theme_findings)
        _refresh_summary(report)
    return report


def _apply_stability_guards(
    report: dict[str, Any],
    *,
    tender_path: Path,
    bid_path: Path,
    force_manual_image_checks: bool = False,
) -> dict[str, Any]:
    report["findings"] = _assign_finding_ids(report.get("findings", []))
    _refresh_summary(report)
    return report


def _parse_review_report_from_raw(
    *,
    raw_output: str,
    prompt: str,
    client: Any,
    backend_name: str,
    tender_path: Path,
    bid_path: Path,
) -> tuple[dict[str, Any], str]:
    try:
        data = extract_json_payload(raw_output)
    except Exception:  # noqa: BLE001
        data = client.ask_json(
            prompt,
            required_top_keys=["requirements", "findings", "summary"],
            task_label=f"初审(JSON重试)：{bid_path.name}",
        )
        raw_output = (
            f"{raw_output}\n\n[JSON_FALLBACK]\n"
            + json.dumps(data, ensure_ascii=False, indent=2)
        )
    if not isinstance(data, dict):
        raise ValueError(f"{backend_name} 返回的审查结果不是 JSON 对象。")
    for key in ("requirements", "findings", "summary"):
        if key not in data:
            raise ValueError(f"{backend_name} 返回缺少关键字段: {key}")

    report = normalize_review_report(data)
    report = _enrich_report_evidence_locations(
        report,
        tender_path=tender_path,
        bid_path=bid_path,
    )
    _refresh_summary(report)
    return report, raw_output


def detect_roles_with_claude(paths: list[str], client: Any) -> tuple[str, str, str]:
    backend_name = "OpenCode" if client.__class__.__name__.lower().startswith("opencode") else "Claude"
    docs = []
    for idx, p in enumerate(paths, start=1):
        path = Path(p).resolve()
        docs.append({"id": f"D{idx}", "path": str(path), "stem": path.stem})
    path_block = "\n".join(f"- {d['id']}: {d['stem']}" for d in docs)
    prompt = render_prompt("role_detect_single.md", file_list=path_block)
    data = client.ask_json(
        prompt,
        required_top_keys=["tender_id", "bid_id"],
        task_label="识别招标文件与投标文件",
    )
    if not isinstance(data, dict):
        raise ValueError(f"{backend_name} 返回格式错误，无法识别招投标文件。")
    tender_id = str(data["tender_id"])
    bid_id = str(data["bid_id"])
    reasoning = str(data.get("reasoning", ""))
    by_id = {d["id"]: d["path"] for d in docs}
    tender_path = by_id.get(tender_id, "")
    bid_path = by_id.get(bid_id, "")

    # 安全兜底。
    if not tender_path or not bid_path:
        # 文件名兜底
        tender_guess = next((p for p in paths if "招标" in Path(p).name), paths[0])
        bid_guess = next((p for p in paths if "投标" in Path(p).name), paths[-1])
        tender_path = str(Path(tender_guess).resolve())
        bid_path = str(Path(bid_guess).resolve())
        reasoning = f"{reasoning}; fallback-by-filename"

    if str(Path(tender_path).resolve()) == str(Path(bid_path).resolve()):
        raise ValueError(f"{backend_name} 未能区分招标与投标文件。")
    return tender_path, bid_path, reasoning


def detect_tender_and_bids_with_claude(
    paths: list[str],
    client: Any,
) -> tuple[str, list[str], str]:
    backend_name = "OpenCode" if client.__class__.__name__.lower().startswith("opencode") else "Claude"
    docs = []
    for idx, p in enumerate(paths, start=1):
        path = Path(p).resolve()
        docs.append({"id": f"D{idx}", "path": str(path), "stem": path.stem})
    path_block = "\n".join(f"- {d['id']}: {d['stem']}" for d in docs)
    prompt = render_prompt("role_detect_multi.md", file_list=path_block)
    data = client.ask_json(
        prompt,
        required_top_keys=["tender_id", "bid_ids"],
        task_label="识别招标文件与多个投标文件",
    )
    if not isinstance(data, dict):
        raise ValueError(f"{backend_name} 返回格式错误，无法识别招投标文件。")
    tender_id = str(data.get("tender_id", ""))
    bid_ids_raw = data.get("bid_ids", [])
    reasoning = str(data.get("reasoning", ""))
    bid_ids = [str(x) for x in bid_ids_raw] if isinstance(bid_ids_raw, list) else []

    by_id = {d["id"]: d["path"] for d in docs}
    tender_path = by_id.get(tender_id, "")
    bid_paths = [by_id.get(x, "") for x in bid_ids]
    bid_paths = [x for x in bid_paths if x and x != tender_path]

    # 安全兜底。
    if not tender_path:
        tender_guess = next((p for p in paths if "招标" in Path(p).name), paths[0])
        tender_path = str(Path(tender_guess).resolve())
        reasoning = f"{reasoning}; fallback-tender-by-filename"

    if not bid_paths:
        bid_by_name = [
            str(Path(p).resolve()) for p in paths if ("投标" in Path(p).name) and (str(Path(p).resolve()) != tender_path)
        ]
        bid_paths = bid_by_name
        if not bid_paths:
            bid_paths = [str(Path(p).resolve()) for p in paths if str(Path(p).resolve()) != tender_path]
        reasoning = f"{reasoning}; fallback-bids-by-filename"

    if not bid_paths:
        raise ValueError("未识别到投标文件。")
    return str(Path(tender_path).resolve()), bid_paths, reasoning


def run_bid_review_with_claude(
    *,
    tender_path: str,
    bid_path: str,
    client: Any,
    extra_instruction: str = "",
    user_instruction: str = "",
) -> tuple[dict[str, Any], str]:
    backend_name = "OpenCode" if client.__class__.__name__.lower().startswith("opencode") else "Claude"
    tender_path_obj = Path(tender_path).resolve()
    bid_path_obj = Path(bid_path).resolve()
    workspace_dir = prompt_safe_path(str(tender_path_obj.parent))
    tender_stem = tender_path_obj.stem
    bid_stem = bid_path_obj.stem
    tender_outline = _collect_tender_outline(tender_path_obj)
    bid_outline = _collect_bid_outline(bid_path_obj)
    min_requirement_count = _estimate_min_requirement_count(
        tender_outline=tender_outline,
        bid_outline=bid_outline,
    )
    tender_document_map = compact_text_for_prompt(
        _format_tender_outline_for_prompt(tender_outline),
        3000,
    )
    bid_document_map = compact_text_for_prompt(
        _format_bid_outline_for_prompt(bid_outline, bid_path=bid_path_obj),
        4000,
    )
    instruction = compact_text_for_prompt(extra_instruction.strip(), 2000) if extra_instruction else "无"
    user_ins = compact_text_for_prompt(user_instruction.strip(), 2000) if user_instruction else "无"
    prompt = render_prompt(
        "review_main.md",
        workspace_dir=workspace_dir,
        tender_stem=tender_stem,
        bid_stem=bid_stem,
        tender_path=str(tender_path_obj),
        bid_path=str(bid_path_obj),
        user_instruction=user_ins,
        instruction=instruction,
        tender_document_map=tender_document_map,
        bid_document_map=bid_document_map,
        minimum_requirement_count=str(min_requirement_count),
    )
    require_word_extract = bid_path_obj.suffix.lower() == ".docx"
    ocr_required = _instruction_requires_ocr(user_instruction, extra_instruction) or (
        require_word_extract and _docx_ocr_required_by_default()
    )
    word_ocr_fully_covered = not (ocr_required and require_word_extract)
    original_timeout = client.timeout_sec
    # OCR全量处理（特别是docx图片较多时）需要更长超时，避免中途失败。
    if ocr_required and require_word_extract and client.timeout_sec < 7200:
        client.timeout_sec = 7200
    try:
        with _prefer_claude_sdk_review_tools(client):
            prompt = _append_no_write_enforcement(prompt)
            raw_output = client.ask_text(prompt, task_label=f"初审：{bid_path_obj.name}")
            first_guard = _collect_review_guard_state(
                tool_calls=client.get_last_tool_calls(),
                tool_uses=client.get_last_tool_uses(),
                ocr_required=ocr_required,
                require_word_extract=require_word_extract,
                bid_path=bid_path_obj,
            )
            need_retry = bool(first_guard.get("has_forbidden_write", False)) or not bool(first_guard.get("ocr_guard_ok", True))
            if need_retry:
                retry_prompt = prompt
                if not bool(first_guard.get("ocr_guard_ok", True)):
                    retry_prompt = _append_ocr_enforcement(retry_prompt, require_word_extract=require_word_extract)
                if require_word_extract and not bool(first_guard.get("word_ocr_coverage_ok", True)):
                    retry_prompt = (
                        retry_prompt
                        + "\n你上一次未完成 Word 提图全量 OCR。"
                        + str(first_guard.get("word_ocr_coverage_detail", ""))
                        + "请严格覆盖提图目录中的全部图片。"
                    )
                if bool(first_guard.get("has_forbidden_write", False)):
                    retry_prompt = _append_no_write_enforcement(retry_prompt)
                retry_output = client.ask_text(retry_prompt, task_label=f"初审重试(约束强制)：{bid_path_obj.name}")
                retry_guard = _collect_review_guard_state(
                    tool_calls=client.get_last_tool_calls(),
                    tool_uses=client.get_last_tool_uses(),
                    ocr_required=ocr_required,
                    require_word_extract=require_word_extract,
                    bid_path=bid_path_obj,
                )
                missing_requirements = [str(x) for x in retry_guard.get("missing_requirements", [])]
                if missing_requirements:
                    raise ClaudeCallError(
                        f"审查阶段缺少必要MCP调用（{', '.join(missing_requirements)}），已按强制规则重试1次仍失败。"
                    )
                if require_word_extract and not bool(retry_guard.get("word_ocr_coverage_ok", True)):
                    raise ClaudeCallError(
                        "Word图片OCR未全量覆盖，已按强制规则重试1次仍失败。"
                        + str(retry_guard.get("word_ocr_coverage_detail", ""))
                    )
                if bool(retry_guard.get("has_forbidden_write", False)) and _strict_fail_on_forbidden_write():
                    raise ClaudeCallError("审查阶段检测到写文件/脚本执行行为，已按只读规则重试1次仍失败。")
                raw_output = retry_output
                active_guard = retry_guard
            else:
                active_guard = first_guard
            if require_word_extract and not bool(active_guard.get("word_ocr_coverage_ok", True)):
                raise ClaudeCallError(
                    "Word图片OCR未全量覆盖。"
                    + str(active_guard.get("word_ocr_coverage_detail", ""))
                )
            if ocr_required and require_word_extract:
                word_ocr_fully_covered = bool(active_guard.get("word_ocr_coverage_ok", True))
            report, raw_output = _parse_review_report_from_raw(
                raw_output=raw_output,
                prompt=prompt,
                client=client,
                backend_name=backend_name,
                tender_path=tender_path_obj,
                bid_path=bid_path_obj,
            )
            if _completion_gate_enabled():
                raw_data = extract_json_payload(raw_output)
                completion_failures = _evaluate_review_completion(
                    raw_data,
                    tender_outline=tender_outline,
                    bid_outline=bid_outline,
                    min_requirement_count=min_requirement_count,
                    require_word_extract=require_word_extract,
                    ocr_required=ocr_required,
                )
                if completion_failures:
                    completion_retry_prompt = _append_completion_enforcement(
                        prompt,
                        tender_document_map=tender_document_map,
                        bid_document_map=bid_document_map,
                        min_requirement_count=min_requirement_count,
                        reasons=completion_failures,
                    )
                    completion_retry_raw = client.ask_text(
                        completion_retry_prompt,
                        task_label=f"初审重试(全文完成门槛)：{bid_path_obj.name}",
                    )
                    report, completion_retry_raw = _parse_review_report_from_raw(
                        raw_output=completion_retry_raw,
                        prompt=completion_retry_prompt,
                        client=client,
                        backend_name=backend_name,
                        tender_path=tender_path_obj,
                        bid_path=bid_path_obj,
                    )
                    raw_data = extract_json_payload(completion_retry_raw)
                    retry_completion_failures = _evaluate_review_completion(
                        raw_data,
                        tender_outline=tender_outline,
                        bid_outline=bid_outline,
                        min_requirement_count=min_requirement_count,
                        require_word_extract=require_word_extract,
                        ocr_required=ocr_required,
                    )
                    if retry_completion_failures:
                        raise ClaudeCallError(
                            "审查结果未满足全文阅读完成门槛："
                            + "；".join(retry_completion_failures)
                        )
                    raw_output = f"{raw_output}\n\n[COMPLETION_RETRY]\n{completion_retry_raw}"
            location_gaps = _find_precise_location_gaps(report, bid_path=bid_path_obj)
            if location_gaps:
                location_retry_prompt = _append_precise_location_enforcement(
                    prompt,
                    bid_path=bid_path_obj,
                    gaps=location_gaps,
                )
                location_retry_raw = client.ask_text(
                    location_retry_prompt,
                    task_label=f"初审重试(精确定位)：{bid_path_obj.name}",
                )
                retry_report, location_retry_raw = _parse_review_report_from_raw(
                    raw_output=location_retry_raw,
                    prompt=location_retry_prompt,
                    client=client,
                    backend_name=backend_name,
                    tender_path=tender_path_obj,
                    bid_path=bid_path_obj,
                )
                location_retry_guard = _collect_review_guard_state(
                    tool_calls=client.get_last_tool_calls(),
                    tool_uses=client.get_last_tool_uses(),
                    ocr_required=ocr_required,
                    require_word_extract=require_word_extract,
                    bid_path=bid_path_obj,
                )
                location_retry_failures = _describe_review_guard_failures(
                    location_retry_guard,
                    ocr_required=ocr_required,
                    require_word_extract=require_word_extract,
                )
                if bool(location_retry_guard.get("has_forbidden_write", False)) and _strict_fail_on_forbidden_write():
                    raise ClaudeCallError("精确定位重试阶段检测到写文件/脚本执行行为，已按只读规则跳过采纳。")
                if location_retry_failures:
                    raw_output = (
                        f"{raw_output}\n\n[LOCATION_RETRY_SKIPPED]\n"
                        + "；".join(location_retry_failures)
                        + f"\n{location_retry_raw}"
                    )
                else:
                    merged_report, merged = _merge_precise_location_retry_report(report, retry_report)
                    if merged:
                        report = merged_report
                        raw_output = f"{raw_output}\n\n[LOCATION_RETRY]\n{location_retry_raw}"
                    else:
                        raw_output = f"{raw_output}\n\n[LOCATION_RETRY_SKIPPED]\n{location_retry_raw}"
    finally:
        client.timeout_sec = original_timeout

    enable_second_pass = os.getenv("BID_REVIEW_ENABLE_SECOND_PASS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    force_manual_image_checks = require_word_extract and ocr_required and (not word_ocr_fully_covered)
    if not enable_second_pass:
        report = _apply_stability_guards(
            report,
            tender_path=tender_path_obj,
            bid_path=bid_path_obj,
            force_manual_image_checks=force_manual_image_checks,
        )
        merged_raw = f"{raw_output}\n\n[SECOND_PASS]\nSKIPPED_BY_DEFAULT"
        return report, merged_raw

    # 二次复核：专找初审遗漏项。
    initial_json = json.dumps(report, ensure_ascii=False, indent=2)
    initial_json = compact_text_for_prompt(initial_json, 8000)
    second_prompt = render_prompt(
        "review_second_pass.md",
        workspace_dir=workspace_dir,
        tender_stem=tender_stem,
        bid_stem=bid_stem,
        tender_path=str(tender_path_obj),
        bid_path=str(bid_path_obj),
        user_instruction=user_ins,
        initial_json=initial_json,
    )
    with _prefer_claude_sdk_review_tools(client):
        second_prompt = _append_no_write_enforcement(second_prompt)
        second_raw = client.ask_text(second_prompt, task_label=f"二次复核：{bid_path_obj.name}")
        if _has_forbidden_write_tool_call(client.get_last_tool_uses()):
            second_retry = _append_no_write_enforcement(second_prompt)
            second_raw = client.ask_text(second_retry, task_label=f"二次复核重试(只读强制)：{bid_path_obj.name}")
            if _has_forbidden_write_tool_call(client.get_last_tool_uses()) and _strict_fail_on_forbidden_write():
                raise ClaudeCallError("二次复核阶段检测到写文件/脚本执行行为，已按只读规则重试1次仍失败。")
    try:
        second_data = extract_json_payload(second_raw)
        add_findings = _normalize_findings(second_data.get("additional_findings", []))
    except Exception:  # noqa: BLE001
        add_findings = []
    if add_findings:
        temp_report = _enrich_report_evidence_locations(
            {"findings": add_findings},
            tender_path=tender_path_obj,
            bid_path=bid_path_obj,
        )
        add_findings = temp_report.get("findings", add_findings)
    if add_findings:
        report["findings"] = _assign_finding_ids(report["findings"] + add_findings)
        _refresh_summary(report)

    # 稳定性兜底：对可确定的不符合项做规则化补齐/归一，降低多次运行抖动。
    report = _apply_stability_guards(
        report,
        tender_path=tender_path_obj,
        bid_path=bid_path_obj,
        force_manual_image_checks=force_manual_image_checks,
    )

    merged_raw = f"{raw_output}\n\n[SECOND_PASS]\n{second_raw}"
    return report, merged_raw
