#!/usr/bin/env python3
"""Build a Word operations manual from a saved workspace JSON."""
from __future__ import annotations
import argparse, base64, io, json, copy, re
from pathlib import Path
from typing import Any
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = ROOT / "backend" / "src" / "main" / "resources" / "templates" / "操作手册模板.docx"

def text(value: Any, fallback: str = "") -> str:
    return str(value if value is not None else fallback).strip()

def screenshot_operation(data: dict[str, Any]) -> str:
    value = text(data.get("operation")) or text(data.get("contentSummary"))
    value = re.sub(r"^截图内容\s*[:：]\s*", "", value).strip()
    return value[1:-1].strip() if value.startswith("【") and value.endswith("】") else value

def generated_for(generated: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    bucket = "screenshots" if node.get("type") in ("screenshot", "screenshot-group") else "nodes"
    return (generated.get(bucket) or {}).get(node.get("id")) or {}

def sort_key(node: dict[str, Any]) -> tuple[float, float, str]:
    return (float(node.get("y") or 0), float(node.get("x") or 0), text(node.get("name")))

def build_tree(nodes: list[dict[str, Any]], links: list[dict[str, Any]]):
    by_id = {text(node.get("id")): node for node in nodes}
    children = {key: [] for key in by_id}; incoming = set()
    for link in links:
        parent, child = by_id.get(text(link.get("fromId"))), by_id.get(text(link.get("toId")))
        if parent and child and parent is not child:
            children[text(parent.get("id"))].append(child); incoming.add(text(child.get("id")))
    for values in children.values(): values.sort(key=sort_key)
    roots = sorted((node for node in nodes if text(node.get("id")) not in incoming), key=sort_key)
    return roots, children

def inferred_level(node: dict[str, Any], depth: int) -> int:
    if depth > 0: return min(depth, 9)
    return {"system": 1, "module": 2, "page": 3}.get(text(node.get("type")), 4)

def remove_style_numbering(style) -> None:
    ppr = style._element.find(qn("w:pPr"))
    if ppr is not None:
        numpr = ppr.find(qn("w:numPr"))
        if numpr is not None: ppr.remove(numpr)

def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr(); shd = OxmlElement("w:shd"); shd.set(qn("w:fill"), fill); tc_pr.append(shd)

def style_document(document: Document) -> None:
    section = document.sections[0]; section.top_margin = Inches(.75); section.bottom_margin = Inches(.75); section.left_margin = Inches(.85); section.right_margin = Inches(.85)
    for name, size, bold in (("Normal", 10.5, False), ("Title", 22, True), ("Heading 1", 16, True), ("Heading 2", 13, True), ("Heading 3", 11.5, True)):
        if name not in [style.name for style in document.styles]:
            document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style = document.styles[name]; style.font.name = "宋体"; style._element.rPr.rFonts.set(qn("w:ascii"), "宋体"); style._element.rPr.rFonts.set(qn("w:hAnsi"), "宋体"); style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体"); style.font.size = Pt(size); style.font.bold = bold; style.font.color.rgb = RGBColor(0, 0, 0); remove_style_numbering(style)
    names = [style.name for style in document.styles]
    for index in range(4, 10):
        name = f"Heading {index}"
        if name not in names: document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style = document.styles[name]; style.base_style = document.styles["Heading 3"]; style.font.name = "宋体"; style._element.rPr.rFonts.set(qn("w:ascii"), "宋体"); style._element.rPr.rFonts.set(qn("w:hAnsi"), "宋体"); style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体"); style.font.size = Pt(max(9, 11 - (index - 3) * .3)); style.font.bold = True; style.font.color.rgb = RGBColor(0, 0, 0); remove_style_numbering(style)
    for style_name in ("toc 1", "toc 2", "toc 3", "toc 4"):
        if style_name in [style.name for style in document.styles]: remove_style_numbering(document.styles[style_name])

def add_profile_table(document: Document, profile: dict[str, Any]) -> None:
    table = document.add_table(rows=1, cols=2); table.style = "Table Grid"
    table.rows[0].cells[0].text = "字段"; table.rows[0].cells[1].text = "内容"
    for cell in table.rows[0].cells:
        set_cell_shading(cell, "4F6356")
        for run in cell.paragraphs[0].runs: run.font.color.rgb = RGBColor(255, 255, 255); run.font.bold = True
    labels = {"name":"软件全称", "shortName":"软件简称", "version":"版本号", "owner":"著作权人", "purpose":"开发目的", "industry":"面向行业", "function":"主要功能", "feature":"技术特点", "completionDate":"开发完成日期"}
    for key, label in labels.items():
        cells = table.add_row().cells; cells[0].text = label; cells[1].text = text(profile.get(key), f"<{key}>")

def add_component(document: Document, node: dict[str, Any], generated: dict[str, Any], children: dict[str, list[dict[str, Any]]], depth: int, seen: set[str], number: str = "3") -> None:
    node_id = text(node.get("id"))
    if node_id in seen: return
    seen.add(node_id); name = text(node.get("name"), "<ComponentName>"); data = generated_for(generated, node)
    is_screenshot = node.get("type") in ("screenshot", "screenshot-group")
    if not is_screenshot:
        heading = document.add_heading(text(data.get("title"), name), level=inferred_level(node, depth)); strip_numbering(heading)
        add_plain_paragraph(document, text(data.get("contentSummary"), "<ContentSummary>"))
    else:
        images = [node.get("image")] if node.get("type") == "screenshot" else [item.get("image") for item in node.get("screenshots") or []]
        heading = document.add_heading(text(data.get("title"), name), level=inferred_level(node, depth)); strip_numbering(heading)
        add_plain_paragraph(document, screenshot_operation(data))
        for data_url in images:
            add_image(document, text(data_url))
    for index, child in enumerate(children.get(node_id, []), 1):
        child_number = f"{number}.{index}"
        add_component(document, child, generated, children, depth + 1, seen, child_number)

def add_plain_paragraph(document: Document, value: str):
    paragraph = document.add_paragraph(value)
    strip_numbering(paragraph)
    return paragraph

def add_image(document: Document, data_url: str) -> None:
    if not data_url.startswith("data:image/") or "," not in data_url:
        return
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1])
        paragraph = document.add_paragraph(); strip_numbering(paragraph)
        paragraph.add_run().add_picture(io.BytesIO(raw), width=Inches(6.25))
    except (ValueError, OSError):
        return

def clear_paragraph(paragraph) -> None:
    for run in list(paragraph.runs):
        run._element.getparent().remove(run._element)

def rewrite_toc_paragraph(paragraph, label: str, page: str = "<PageNumber>") -> None:
    """Rewrite a TOC row while retaining the reference paragraph's leader/tab layout."""
    # Keep pPr (style, right tab and dot leader) and remove only content runs.
    for child in list(paragraph._p):
        if child.tag != qn("w:pPr"):
            paragraph._p.remove(child)
    run = OxmlElement("w:r")
    t = OxmlElement("w:t"); t.text = label; run.append(t); paragraph._p.append(run)
    tab_run = OxmlElement("w:r"); tab_run.append(OxmlElement("w:tab")); paragraph._p.append(tab_run)
    page_run = OxmlElement("w:r"); pt = OxmlElement("w:t"); pt.text = page; page_run.append(pt); paragraph._p.append(page_run)
    strip_numbering(paragraph)

def strip_numbering(paragraph) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    numpr = ppr.find(qn("w:numPr"))
    if numpr is not None: ppr.remove(numpr)

def insert_after(paragraph, text_value: str, style: str):
    new = OxmlElement("w:p")
    ppr = OxmlElement("w:pPr"); pstyle = OxmlElement("w:pStyle"); pstyle.set(qn("w:val"), style); ppr.append(pstyle); new.append(ppr)
    run = OxmlElement("w:r"); t = OxmlElement("w:t"); t.text = text_value; run.append(t); new.append(run)
    paragraph._p.addnext(new)
    return new

def template_skeleton(document: Document, workspace: dict[str, Any]) -> None:
    """Keep the supplied manual's cover, TOC typography, header and footer."""
    paragraphs = document.paragraphs
    profile = workspace.get("profile") or {}
    # Cover paragraphs vary slightly between Word/WPS versions; identify them by
    # their position among non-empty paragraphs before the TOC heading.
    toc_heading = next((i for i, p in enumerate(paragraphs) if "目录" in p.text), len(paragraphs))
    cover = [p for p in paragraphs[:toc_heading] if p.text.strip()]
    if cover: cover[0].text = text(profile.get("name"), "<DocumentTitle>")
    if len(cover) > 1: cover[1].text = "操作手册"
    if len(cover) > 2: cover[-1].text = text(profile.get("owner"), "<Owner>")
    # Keep the cover, TOC, introduction and environment rows; remove only the
    # reference component body after paragraph 60.
    body = document._element.body
    kept = 0
    for child in list(body):
        if child.tag == qn("w:p"):
            if kept >= 61: body.remove(child)
            kept += 1
    paragraphs = document.paragraphs
    profile = workspace.get("profile") or {}
    if len(paragraphs) > 52: paragraphs[52].text = text(profile.get("purpose"), "<Purpose>")
    if len(paragraphs) > 54: paragraphs[54].text = "运行的硬件、软件环境的描述如下："
    env = (("服务端操作系统：", "runOs"), ("服务端运行环境：", "runHardware"), ("数据库支持：", "support"), ("协议支持：", "languages"), ("硬件支持：", "runHardware"), ("客户端要求：", "support"))
    for index, (label, key) in enumerate(env):
        if len(paragraphs) > 55 + index: paragraphs[55 + index].text = label + text(profile.get(key)) + "；"
    # Replace the sample TOC rows and add rows when the current workspace has more entries.
    toc = [("一、 系统简介", "toc 1"), ("二、 运行环境", "toc 1")]
    roots, children = build_tree(workspace.get("nodes") or [], workspace.get("connections") or [])
    def walk(node, prefix, level):
        label = f"三、 {text(node.get('name'), '<ComponentName>')}" if level == 1 else f"{prefix} {text(node.get('name'), '<ComponentName>')}"
        toc.append((label, f"toc {min(level,4)}"))
        for index, child in enumerate(children.get(text(node.get("id")), []), 1): walk(child, f"{prefix}.{index}", level + 1)
    for index, root in enumerate(roots, 1): walk(root, str(index + 2), 1)
    toc_start = next((i for i, p in enumerate(paragraphs) if p.style.name.lower().startswith("toc") and p.text.strip()), 25)
    toc_end = toc_start
    while toc_end < len(paragraphs):
        p = paragraphs[toc_end]
        if p.text.strip() and not p.style.name.lower().startswith("toc"):
            break
        toc_end += 1
    existing = paragraphs[toc_start:toc_end]
    sample_ppr = copy.deepcopy(existing[0]._p.pPr) if existing else None
    body = document._element.body
    # Remove all old TOC rows. They are regenerated because workspaces can have
    # more or fewer rows than the reference document.
    for paragraph in existing:
        body.remove(paragraph._p)
    anchor = next((child for child in body if child.tag == qn("w:sectPr")), None)
    for label, style in toc:
        p = OxmlElement("w:p")
        ppr = copy.deepcopy(sample_ppr) if sample_ppr is not None else OxmlElement("w:pPr")
        # Preserve the reference right tab/leader but update the paragraph style.
        pstyle = ppr.find(qn("w:pStyle"))
        if pstyle is None:
            pstyle = OxmlElement("w:pStyle"); ppr.insert(0, pstyle)
        # Use the document's normal paragraph style so the literal title text is
        # rendered by Word/WPS; retain the reference tab leader in pPr.
        toc_style_ids = {"toc 1": "26", "toc 2": "30", "toc 3": "19", "toc 4": "27"}
        pstyle.set(qn("w:val"), toc_style_ids.get(style, "26"))
        p.append(ppr)
        r = OxmlElement("w:r"); rp = OxmlElement("w:rPr"); color = OxmlElement("w:color"); color.set(qn("w:val"), "000000"); rp.append(color); r.append(rp); t = OxmlElement("w:t"); t.text = label; r.append(t); p.append(r)
        tr = OxmlElement("w:r"); tr.append(OxmlElement("w:tab")); p.append(tr)
        pr = OxmlElement("w:r"); rpp = OxmlElement("w:rPr"); pc = OxmlElement("w:color"); pc.set(qn("w:val"), "000000"); rpp.append(pc); pr.append(rpp); pt = OxmlElement("w:t"); pt.text = "<PageNumber>"; pr.append(pt); p.append(pr)
        if anchor is not None: anchor.addprevious(p)
        else: body.append(p)

def add_runtime_environment(document: Document, profile: dict[str, Any]) -> None:
    document.add_heading("系统简介", 1)
    document.add_paragraph(text(profile.get("purpose"), "<Purpose>"))
    document.add_heading("运行环境", 1)
    document.add_paragraph("运行的硬件、软件环境的描述如下：")
    for value in (profile.get("runOs"), profile.get("runHardware"), profile.get("support")):
        if text(value): document.add_paragraph(text(value))

def export(workspace: dict[str, Any], output: Path, template: Path | None = None) -> None:
    source = template or DEFAULT_TEMPLATE; document = Document(str(source)) if source.exists() else Document();
    if not source.exists(): style_document(document)
    profile = workspace.get("profile") or {}
    if source.exists() and len(document.paragraphs) >= 52:
        template_skeleton(document, workspace)
    else:
        document.add_paragraph(text(profile.get("name"), "<DocumentTitle>"), style="Title")
        document.add_paragraph(f"版本：{text(profile.get('version'), '<Version>')}")
        add_runtime_environment(document, profile)
    nodes = workspace.get("nodes") or []; roots, children = build_tree(nodes, workspace.get("connections") or []); generated = workspace.get("generated") or {}; seen: set[str] = set()
    for root in roots: add_component(document, root, generated, children, 0, seen)
    for node in sorted(nodes, key=sort_key):
        if text(node.get("id")) not in seen: add_component(document, node, generated, children, 0, seen)
    output.parent.mkdir(parents=True, exist_ok=True); document.save(str(output))

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("workspace"); parser.add_argument("output"); parser.add_argument("--template", default=str(DEFAULT_TEMPLATE)); args = parser.parse_args(); export(json.loads(Path(args.workspace).read_text(encoding="utf-8")), Path(args.output), Path(args.template))

if __name__ == "__main__": main()
