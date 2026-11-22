"""Prepare an approved R11 attachment for the portal without changing its original."""
import base64
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from xml.sax.saxutils import escape
import zipfile

from fastapi import HTTPException
from pypdf import PdfReader, PdfWriter

LIMIT = 20 * 1024 * 1024
DOCUMENTS = {".docx", ".doc", ".odt", ".rtf"}
TEXT = {".txt", ".md", ".java", ".js", ".ts", ".py", ".go", ".c", ".cpp", ".cs",
        ".html", ".css", ".sql", ".json", ".xml", ".yaml", ".yml", ".sh", ".vue"}


def prepare_pdf(content: bytes, suffix: str, excerpt: bool) -> bytes:
    if not content or len(content) > LIMIT:
        raise HTTPException(422, "附件为空或超过 20 MB")
    try:
        if suffix == ".chapters":
            from docx import Document
            from docx.shared import Inches
            document = Document()
            for chapter in json.loads(content):
                document.add_heading(chapter["title"], level=1)
                for paragraph in chapter["body"].splitlines():
                    document.add_paragraph(paragraph)
                screenshot = chapter.get("screenshot")
                if screenshot and screenshot.startswith("data:image/"):
                    image = base64.b64decode(screenshot.split(",", 1)[1], validate=True)
                    document.add_picture(io.BytesIO(image), width=Inches(6))
            buffer = io.BytesIO()
            document.save(buffer)
            content, suffix = buffer.getvalue(), ".docx"
        pdf = content if suffix == ".pdf" else convert_document(content, suffix)
        reader = PdfReader(io.BytesIO(pdf))
        if not len(reader.pages):
            raise ValueError("empty PDF")
        if excerpt and len(reader.pages) > 60:
            # Keep the original order and retain the two continuous page ranges.
            writer = PdfWriter()
            writer.append(reader, pages=(0, 30), import_outline=False)
            writer.append(reader, pages=(len(reader.pages) - 30, len(reader.pages)), import_outline=False)
            output = io.BytesIO()
            writer.write(output)
            pdf = output.getvalue()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "无法读取或转换该附件，请检查文件是否损坏或加密") from exc
    if len(pdf) > LIMIT:
        raise HTTPException(422, "转换后的 PDF 超过官网 20 MB 上限")
    return pdf


def convert_document(content: bytes, suffix: str) -> bytes:
    if suffix not in DOCUMENTS | TEXT:
        raise HTTPException(422, "此格式无法自动转换，请提供 PDF、Word、ODT、RTF 或 UTF-8 文本")
    if suffix in {".docx", ".odt"}:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
                raise HTTPException(422, "文档解压后过大")
    office = os.getenv("SOFFICE_PATH") or shutil.which("soffice") or shutil.which("libreoffice")
    if not office:
        raise HTTPException(503, "服务器未配置 LibreOffice，暂时无法转换文档")
    with tempfile.TemporaryDirectory(prefix="r11-pdf-") as directory:
        work = Path(directory)
        if suffix in TEXT:
            content = content.decode("utf-8-sig").encode("utf-8")
            suffix = ".txt"
        source = work / ("material" + suffix)
        source.write_bytes(content)
        # Use a dedicated LibreOffice profile and disable macro execution.
        profile = work / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user/registrymodifications.xcu").write_text(
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '</item></oor:items>', encoding="utf-8")
        command = [office, "-env:UserInstallation=" + profile.as_uri(),
                   "--headless", "--norestore", "--convert-to", "pdf:writer_pdf_Export",
                   "--outdir", str(work)]
        if suffix == ".txt":
            command.append("--infilter=Text (encoded):UTF8,LF")
        env = os.environ.copy()
        mac_fonts = [Path(path) for path in ("/System/Library/Fonts", "/Library/Fonts",
                     str(Path.home() / "Library/Fonts"), "/System/Library/AssetsV2/com_apple_MobileAsset_Font7")]
        if not env.get("FONTCONFIG_FILE") and mac_fonts[0].is_dir():
            config = work / "fonts.conf"
            directories = "".join(f"<dir>{escape(str(path))}</dir>" for path in mac_fonts if path.is_dir())
            config.write_text("<fontconfig>" + directories + "</fontconfig>", encoding="utf-8")
            env["FONTCONFIG_FILE"] = str(config)
        subprocess.run([*command, str(source)], check=True, timeout=55, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with (work / "material.pdf").open("rb") as converted:
            return converted.read(LIMIT + 1)
