"""Fill the project Word template using analyzed content and captured evidence."""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
from manual_capture import ManualError


def render_manual(template: Path, output: Path, project, basic, overview, modules, pages, operations, prose, shots, images):
    doc = Document(template)
    body = doc.element.body
    # Retain the cover, TOC title, section break and page furniture from the reference.
    paragraphs = doc.paragraphs
    break_node = next((node for node in body if node.xpath('./w:pPr/w:sectPr')), None)
    if (len(paragraphs) < 25 or break_node is None or paragraphs[24].text.replace(' ', '') != '目录'
            or any(not paragraphs[i].runs for i in (6, 8, 19))):
        raise ManualError('Word 模板的封面、目录或分节结构不匹配。')
    cover, subtitle, owner = paragraphs[6], paragraphs[8], paragraphs[19]
    for node in list(body)[25:]:
        if node is not break_node and node.tag != qn('w:sectPr'):
            body.remove(node)
    cover.runs[0].text = f'{project["name"]} {project["version"]}'.strip()
    for run in cover.runs[1:]:
        run.text = ''
    for i, run in enumerate(subtitle.runs):
        run.text = '操作手册' if i == 0 else ''
    for i, run in enumerate(owner.runs):
        run.text = basic.get('著作权人', '') if i == 0 else ''
    doc.core_properties.title = f'{project["name"]} 操作手册'
    doc.core_properties.author = ''
    doc.core_properties.last_modified_by = ''
    doc.core_properties.subject = ''
    doc.core_properties.keywords = ''
    doc.core_properties.comments = ''
    # Old sample images and custom data must not survive in the new file.
    used = {value for node in doc.element.iter() for key, value in node.attrib.items()
            if key.startswith('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}')}
    for rid, rel in list(doc.part.rels.items()):
        if rel.reltype.rsplit('/', 1)[-1] in {'image', 'hyperlink', 'customXml'} and rid not in used:
            del doc.part.rels[rid]
    package = doc.part.package
    for rid, rel in list(package.rels.items()):
        if rel.reltype.endswith('/custom-properties'):
            del package.rels[rid]

    heading_id = 0

    def heading(text, level):
        nonlocal heading_id
        heading_id += 1
        anchor = f'ManualSection{heading_id}'
        title = doc.add_heading(text, level)
        start = OxmlElement('w:bookmarkStart')
        start.set(qn('w:id'), str(heading_id))
        start.set(qn('w:name'), anchor)
        title._p.insert(1, start)
        end = OxmlElement('w:bookmarkEnd')
        end.set(qn('w:id'), str(heading_id))
        title._p.append(end)
        entry = doc.add_paragraph(style=f'toc {level}')
        entry.paragraph_format.left_indent = Inches(0.24 * (level - 1))
        entry.paragraph_format.space_after = Inches(0.04)
        entry.paragraph_format.first_line_indent = Inches(0)
        link = OxmlElement('w:hyperlink')
        link.set(qn('w:anchor'), anchor)
        run = entry.add_run(text)
        link.append(run._r)
        entry._p.append(link)
        break_node.addprevious(entry._p)

    heading('系统简介', 1)
    doc.add_paragraph(overview)
    heading('基础信息与运行环境', 1)
    if basic:
        for label, value in basic.items():
            item = doc.add_paragraph(f'{label}：{value}')
            if len(value) < 90:
                item.paragraph_format.line_spacing = 1.15
                item.paragraph_format.space_after = Inches(0.04)
    else:
        doc.add_paragraph('以项目基础信息填报页为准。')
    heading('功能操作说明', 1)
    children = {}
    for module in modules:
        children.setdefault(module.parentId, []).append(module)
    shot_by_target = {(s.pageId, s.operationId): s for s in shots}
    figure = 0

    def picture(page, operation=None):
        nonlocal figure
        shot = shot_by_target.get((page.id, operation))
        if not shot:
            return
        figure += 1
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.keep_with_next = True
        paragraph.paragraph_format.first_line_indent = Inches(0)
        label = f'图 {figure}  {shot.title}'
        if shot.id in images:
            drawing = paragraph.add_run().add_picture(str(images[shot.id]), width=Inches(5.65))
            drawing._inline.docPr.set('descr', shot.title)
        else:
            paragraph.paragraph_format.line_spacing = Inches(1.25)
            paragraph.add_run('\u00a0')
            border = OxmlElement('w:pBdr')
            for side in ('top', 'left', 'bottom', 'right'):
                edge = OxmlElement('w:' + side)
                edge.set(qn('w:val'), 'single')
                edge.set(qn('w:sz'), '4')
                edge.set(qn('w:color'), 'B8C0CC')
                border.append(edge)
            paragraph._p.get_or_add_pPr().insert_element_before(
                border, 'w:shd', 'w:tabs', 'w:spacing', 'w:ind', 'w:jc')
            label = f'图 {figure}  {shot.title}（待补截图，画面应显示「{shot.visibleText}」）'
        caption = doc.add_paragraph(label, style='Caption')
        caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
        caption.paragraph_format.left_indent = Inches(0)
        caption.paragraph_format.first_line_indent = Inches(0)
        caption._p.get_or_add_pPr().get_or_add_numPr().get_or_add_numId().val = 0

    def module_contents(parent, level):
        for module in children.get(parent, []):
            heading(module.title, min(level, 4))
            for page in (p for p in pages if p.moduleId == module.id):
                heading(page.title, min(level + 1, 5))
                doc.add_paragraph(prose[page.id])
                page_shot = shot_by_target.get((page.id, None))
                if page_shot and page_shot.id not in images:
                    doc.add_paragraph('计划路径：' + (' → '.join(x.label for x in page.steps) or '测试站点入口'))
                else:
                    doc.add_paragraph('进入路径：' + (' → '.join(x.label for x in page.steps) or '初始页面'))
                picture(page)
                for operation in (o for o in operations if o.pageId == page.id):
                    p = doc.add_paragraph()
                    p.add_run(operation.title).bold = True
                    p.add_run('：' + operation.description)
                    for n, step in enumerate(operation.instructions, 1):
                        doc.add_paragraph(f'{n}. {step}')
                    picture(page, operation.id)
            module_contents(module.id, level + 1)

    module_contents(None, 2)
    doc.save(output)
