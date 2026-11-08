#!/usr/bin/env python3
from pathlib import Path
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "templates" / "操作手册模板.docx"; OUT.parent.mkdir(parents=True, exist_ok=True)
doc = Document(); section = doc.sections[0]; section.top_margin = Inches(.8); section.bottom_margin = Inches(.8); section.left_margin = Inches(.9); section.right_margin = Inches(.9)
for name, size, bold in (("Normal",10.5,False),("Title",22,True),("Heading 1",16,True),("Heading 2",13,True),("Heading 3",11.5,True)):
    style = doc.styles[name]; style.font.name = ".CJK Symbols Fallback SC"; style._element.rPr.rFonts.set(qn("w:ascii"), ".CJK Symbols Fallback SC"); style._element.rPr.rFonts.set(qn("w:hAnsi"), ".CJK Symbols Fallback SC"); style._element.rPr.rFonts.set(qn("w:eastAsia"), ".CJK Symbols Fallback SC"); style.font.size = Pt(size); style.font.bold = bold; style.font.color.rgb = RGBColor(0,0,0)
doc.add_paragraph("<DocumentTitle>", style="Title"); doc.add_paragraph("版本：<Version>"); doc.add_heading("软件基础信息",1); doc.add_paragraph("<SoftwareProfile>"); doc.add_heading("操作手册",1); doc.add_paragraph("<ManualContent>"); doc.add_heading("导出说明",1); doc.add_paragraph("本文档由操作手册组件自动生成。组件标题级别由父子连线、画布排列和组件类型共同确定。")
doc.save(OUT); print(OUT)
