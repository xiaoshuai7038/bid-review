from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from app.gui.app import create_application
from app.gui.services import BatchReviewData, ReviewRunData
from app.gui.window import MainWindow


@dataclass
class ManualBuildPaths:
    output_dir: Path
    screenshots_dir: Path
    demo_dir: Path
    docx_path: Path


@dataclass
class DemoArtifacts:
    tender_path: Path
    bid_paths: list[Path]
    report_output_dir: Path
    batch_summary_path: Path
    batch_result: BatchReviewData


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a Word user manual with current desktop GUI screenshots.")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/output/user-manual",
        help="Directory where screenshots and the generated .docx manual will be written.",
    )
    return parser


def _set_east_asia_font(run, font_name: str) -> None:
    run.font.name = font_name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)


def _configure_document(document: Document) -> None:
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    section.top_margin = Inches(0.6)
    section.bottom_margin = Inches(0.6)
    section.left_margin = Inches(0.6)
    section.right_margin = Inches(0.6)

    style = document.styles["Normal"]
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(10.5)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")


def _add_title(document: Document, title: str, subtitle: str = "") -> None:
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run(title)
    run.bold = True
    run.font.size = Pt(20)
    _set_east_asia_font(run, "Microsoft YaHei")
    if subtitle:
        subtitle_paragraph = document.add_paragraph()
        subtitle_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        subtitle_run = subtitle_paragraph.add_run(subtitle)
        subtitle_run.font.size = Pt(10.5)
        _set_east_asia_font(subtitle_run, "Microsoft YaHei")


def _add_heading(document: Document, text: str, level: int = 1) -> None:
    paragraph = document.add_paragraph()
    paragraph.style = document.styles[f"Heading {level}"]
    run = paragraph.add_run(text)
    run.bold = True
    _set_east_asia_font(run, "Microsoft YaHei")


def _add_bullet(document: Document, text: str) -> None:
    paragraph = document.add_paragraph(style="List Bullet")
    run = paragraph.add_run(text)
    _set_east_asia_font(run, "Microsoft YaHei")


def _add_paragraph(document: Document, text: str = "") -> None:
    paragraph = document.add_paragraph()
    run = paragraph.add_run(text)
    _set_east_asia_font(run, "Microsoft YaHei")


def _add_screenshot(document: Document, image_path: Path, caption: str) -> None:
    document.add_picture(str(image_path), width=Inches(8.8))
    caption_paragraph = document.add_paragraph()
    caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = caption_paragraph.add_run(caption)
    run.italic = True
    run.font.size = Pt(9)
    _set_east_asia_font(run, "Microsoft YaHei")


def _set_combo_value(combo, value: str) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_paths(output_dir: Path) -> ManualBuildPaths:
    root = output_dir.expanduser().resolve()
    screenshots_dir = root / "screenshots"
    demo_dir = root / "_demo"
    docx_path = root / "bidreview-user-manual.docx"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    demo_dir.mkdir(parents=True, exist_ok=True)
    return ManualBuildPaths(
        output_dir=root,
        screenshots_dir=screenshots_dir,
        demo_dir=demo_dir,
        docx_path=docx_path,
    )


def _build_demo_batch(demo_dir: Path) -> DemoArtifacts:
    tender_path = demo_dir / "招标文件-生产系统升级项目.pdf"
    bid_a = demo_dir / "投标文件-A公司.docx"
    bid_b = demo_dir / "投标文件-B公司.docx"
    _write_text(tender_path, "demo tender")
    _write_text(bid_a, "demo bid a")
    _write_text(bid_b, "demo bid b")

    run_dir = demo_dir / "run-20260318-manual-demo"
    report_json = run_dir / "review_report.json"
    report_md = run_dir / "review_report.md"
    report_docx = run_dir / "review_report.docx"
    batch_summary_path = run_dir / "batch_summary.json"

    report = {
        "summary": {
            "requirement_count": 42,
            "non_compliant_count": 3,
            "risk_count": 2,
            "needs_manual_count": 1,
        },
        "findings": [
            {
                "id": "F001",
                "requirement_id": "R018",
                "status": "non_compliant",
                "issue": "投标文件未提供项目负责人近一年社保证明。",
                "tender_evidence": "招标文件第12页 L8-L12：项目负责人需提供近一年本企业缴纳社保证明。",
                "bid_evidence": "投标文件《项目组成员表》仅列出姓名和岗位，未附社保证明。",
                "recommendation": "补充项目负责人近一年社保证明，并核对社保缴纳主体与投标主体一致。",
            },
            {
                "id": "F002",
                "requirement_id": "R026",
                "status": "risk",
                "issue": "报价汇总页与分项报价页金额存在细微差异，需要人工复核。",
                "tender_evidence": "招标文件第33页 L2-L5：报价应保持总价与分项合计一致。",
                "bid_evidence": "投标文件《报价汇总表》总价与《分项报价表》合计相差 200 元。",
                "recommendation": "复核报价清单，统一总价与分项金额后重新导出最终版报价文件。",
            },
            {
                "id": "F003",
                "requirement_id": "R031",
                "status": "needs_manual",
                "issue": "类似业绩证明扫描件印章不清晰，系统无法确认盖章完整性。",
                "tender_evidence": "招标文件第41页 L15-L18：类似业绩需提供合同关键页及盖章页。",
                "bid_evidence": "投标文件附件中的合同扫描页存在模糊区域，无法确认盖章是否完整。",
                "recommendation": "建议人工复核原始扫描件，必要时补充更清晰的盖章页。",
            },
        ],
    }

    _write_json(report_json, report)
    _write_text(report_md, "# 演示报告\n\n用于生成用户手册。")
    _write_text(report_docx, "demo docx placeholder")

    summary_payload = {
        "tender_path": str(tender_path),
        "role_reasoning": "manual",
        "runs": [
            {
                "bid_path": str(bid_a),
                "output_dir": str(run_dir),
                "json": str(report_json),
                "markdown": str(report_md),
                "docx": str(report_docx),
                "summary": report["summary"],
            },
            {
                "bid_path": str(bid_b),
                "output_dir": str(run_dir),
                "json": str(report_json),
                "markdown": str(report_md),
                "docx": str(report_docx),
                "summary": report["summary"],
            },
        ],
    }
    _write_json(batch_summary_path, summary_payload)

    batch_result = BatchReviewData(
        tender_path=str(tender_path),
        role_reasoning="manual",
        output_dir=run_dir,
        batch_summary_path=batch_summary_path,
        runs=[
            ReviewRunData(
                bid_path=str(bid_a),
                output_dir=run_dir,
                json_path=report_json,
                markdown_path=report_md,
                docx_path=report_docx,
                raw_output_path=None,
                summary=report["summary"],
                report=report,
            ),
            ReviewRunData(
                bid_path=str(bid_b),
                output_dir=run_dir,
                json_path=report_json,
                markdown_path=report_md,
                docx_path=report_docx,
                raw_output_path=None,
                summary=report["summary"],
                report=report,
            ),
        ],
    )
    return DemoArtifacts(
        tender_path=tender_path,
        bid_paths=[bid_a, bid_b],
        report_output_dir=run_dir,
        batch_summary_path=batch_summary_path,
        batch_result=batch_result,
    )


@contextmanager
def _isolated_settings_file(demo_dir: Path):
    settings_path = demo_dir / "manual_settings.json"
    settings_payload = {
        "default_backend": "claude",
        "default_output_dir": str((demo_dir / "results").resolve()),
        "claude_default_model": "claude-sonnet-4-5",
        "default_progress_level": "agent",
        "default_timeout_sec": 1800,
        "default_effort": "low",
        "default_review_profile": "balanced",
        "claude_sdk_base_url": "https://api.anthropic.com",
        "default_instruction": "优先核对资格证明、报价一致性和盖章完整性。",
        "default_user_instruction": "发现证据不足时直接给出可执行整改建议。",
    }
    _write_json(settings_path, settings_payload)
    previous = os.environ.get("BID_REVIEW_GUI_SETTINGS_PATH")
    os.environ["BID_REVIEW_GUI_SETTINGS_PATH"] = str(settings_path)
    try:
        yield settings_path
    finally:
        if previous is None:
            os.environ.pop("BID_REVIEW_GUI_SETTINGS_PATH", None)
        else:
            os.environ["BID_REVIEW_GUI_SETTINGS_PATH"] = previous


def _render_window(app, window: MainWindow, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        app.processEvents()
        window.repaint()
    saved = window.grab().save(str(target))
    if not saved or not target.exists() or target.stat().st_size == 0:
        raise RuntimeError(f"failed to save screenshot: {target}")


def _prepare_home_page(window: MainWindow, batch_result: BatchReviewData) -> None:
    window.current_result = batch_result
    window.home_page.set_recent(batch_result)
    window.status_badge.setText("就绪")
    window._set_current_page(0)


def _prepare_review_page(window: MainWindow, demo: DemoArtifacts) -> None:
    page = window.review_page
    window.status_badge.setText("就绪")
    window._set_current_page(1)
    page.tender_card.set_file(str(demo.tender_path))
    page.bid_card.set_paths([str(path) for path in demo.bid_paths])
    _set_combo_value(page.backend_combo, "claude")
    page.model_edit.setText("claude-sonnet-4-5")
    _set_combo_value(page.progress_combo, "agent")
    _set_combo_value(page.effort_combo, "low")
    _set_combo_value(page.review_profile_combo, "balanced")
    page.output_dir_edit.setText(str(demo.report_output_dir))
    page.timeout_spin.setValue(1800)
    page.instruction_edit.setPlainText("优先关注资格证明、报价一致性和签章完整性。")
    page.user_instruction_edit.setPlainText("需要人工复核时请给出明确补充材料建议。")
    page.clear_progress()


def _prepare_results_page(window: MainWindow, demo: DemoArtifacts) -> None:
    window.current_result = demo.batch_result
    window.results_page.set_result(demo.batch_result)
    window.status_badge.setText("已完成")
    window._set_current_page(2)


def _prepare_settings_page(window: MainWindow, demo: DemoArtifacts) -> None:
    page = window.settings_page
    window.status_badge.setText("就绪")
    window._set_current_page(3)
    _set_combo_value(page.default_backend, "claude")
    page.output_dir.setText(str(demo.report_output_dir))
    page.claude_default_model.setText("claude-sonnet-4-5")
    _set_combo_value(page.default_progress, "agent")
    page.default_timeout.setValue(1800)
    _set_combo_value(page.default_effort, "low")
    _set_combo_value(page.default_review_profile, "balanced")
    page.claude_sdk_base_url.setText("https://api.anthropic.com")
    page.claude_sdk_auth_token.setText("manual-demo-token")
    page.default_instruction.setPlainText("默认说明：优先关注资格证明、报价一致性和盖章完整性。")
    page.default_user_instruction.setPlainText("个人偏好：问题建议要直接、可执行。")


def capture_manual_screenshots(paths: ManualBuildPaths) -> dict[str, Path]:
    screenshots = {
        "home": paths.screenshots_dir / "01-home.png",
        "settings": paths.screenshots_dir / "02-settings.png",
        "review": paths.screenshots_dir / "03-new-review.png",
        "results": paths.screenshots_dir / "04-results.png",
    }
    demo = _build_demo_batch(paths.demo_dir)
    with _isolated_settings_file(paths.demo_dir):
        app = create_application([])
        window = MainWindow()
        window.resize(1600, 980)
        window.show()
        app.processEvents()

        _prepare_home_page(window, demo.batch_result)
        _render_window(app, window, screenshots["home"])

        _prepare_settings_page(window, demo)
        _render_window(app, window, screenshots["settings"])

        _prepare_review_page(window, demo)
        _render_window(app, window, screenshots["review"])

        _prepare_results_page(window, demo)
        _render_window(app, window, screenshots["results"])

        window.close()
        app.quit()
    return screenshots


def build_user_manual(paths: ManualBuildPaths, screenshots: dict[str, Path]) -> Path:
    document = Document()
    _configure_document(document)
    _add_title(document, "标书审查工作台使用手册", "适用于当前 Windows 桌面版 GUI 的日常使用说明")

    _add_heading(document, "1. 使用前准备")
    _add_bullet(document, "确认已拿到完整的桌面交付目录，并从其中启动 BidReviewDesktop.exe。")
    _add_bullet(document, "准备 1 份招标文件，以及 1 份或多份待审查的投标文件。")
    _add_bullet(document, "如需连接 Claude 服务，请先在“默认设置”页面填写服务地址、访问凭证和默认结果保存位置。")

    _add_heading(document, "2. 首页总览")
    _add_paragraph(document, "首页用于快速进入新建审查，或直接打开最近一次审查结果。首次使用时可以先进入“默认设置”完成基础配置。")
    _add_screenshot(document, screenshots["home"], "图 1 首页：可从这里开始新建审查或查看最近结果")

    _add_heading(document, "3. 默认设置")
    _add_paragraph(document, "建议首次使用时先完成默认设置。常用项包括默认审查引擎、默认结果保存位置、Claude 模型、服务地址和访问凭证。访问凭证只保留在当前窗口，不会写入本地设置文件。")
    _add_bullet(document, "默认审查引擎：当前交付建议使用 Claude 引擎。")
    _add_bullet(document, "默认结果保存位置：建议设置为团队约定的项目输出目录。")
    _add_bullet(document, "默认补充说明：适合沉淀团队共用的审查偏好。")
    _add_screenshot(document, screenshots["settings"], "图 2 默认设置：建议先确认输出目录、Claude 模型和访问凭证")

    _add_heading(document, "4. 新建一次审查")
    _add_paragraph(document, "进入“新建审查”后，按从上到下的顺序完成文件和参数设置。程序要求选择 1 份招标文件，并支持一次添加多份投标文件进行批量审查。")
    _add_bullet(document, "先选择招标文件，再添加一份或多份投标文件。")
    _add_bullet(document, "确认模型、结果保存位置、审查策略与超时时间。")
    _add_bullet(document, "点击“开始审查”后，右侧会显示处理进度、详细记录和当前任务状态。")
    _add_screenshot(document, screenshots["review"], "图 3 新建审查：选择文件并确认参数后即可开始审查")

    _add_heading(document, "5. 查看结果")
    _add_paragraph(document, "审查完成后，切换到“查看结果”页面。顶部会展示当前批次概况，中间可以切换不同投标文件，底部的“问题与建议明细”表格用于查看每条问题的结论、证据与处理建议。")
    _add_bullet(document, "“打开结果目录”可直接定位当前运行目录。")
    _add_bullet(document, "“打开结构化结果 / 文本报告 / Word 报告 / 批量汇总”用于打开导出的不同结果文件。")
    _add_bullet(document, "如同一批次有多份投标文件，可通过“投标文件”下拉框切换查看。")
    _add_screenshot(document, screenshots["results"], "图 4 查看结果：按投标文件切换并查看问题明细与导出入口")

    _add_heading(document, "6. 导出文件说明")
    _add_bullet(document, "review_report.json：结构化结果，适合二次处理或接入其他系统。")
    _add_bullet(document, "review_report.md：文本报告，便于快速阅读和发送。")
    _add_bullet(document, "review_report.docx：Word 版报告，适合直接归档或继续编辑。")
    _add_bullet(document, "batch_summary.json：批量汇总结果，记录本批次所有投标文件的摘要。")

    _add_heading(document, "7. 使用建议")
    _add_bullet(document, "优先在“默认设置”里固化常用输出目录和默认说明，减少每次重复填写。")
    _add_bullet(document, "批量审查时，先统一整理好招标文件与多份投标文件，能明显减少来回切换。")
    _add_bullet(document, "如页面显示“需人工复核”，建议结合原始文件重点检查扫描件清晰度、盖章完整性和金额一致性。")

    document.save(paths.docx_path)
    return paths.docx_path


def generate_manual(output_dir: Path) -> tuple[Path, dict[str, Path]]:
    paths = _build_paths(output_dir)
    screenshots = capture_manual_screenshots(paths)
    docx_path = build_user_manual(paths, screenshots)
    return docx_path, screenshots


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir)
    docx_path, screenshots = generate_manual(output_dir)
    manifest = {
        "docx": str(docx_path),
        "screenshots": {name: str(path) for name, path in screenshots.items()},
    }
    (output_dir.expanduser().resolve() / "manual_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
