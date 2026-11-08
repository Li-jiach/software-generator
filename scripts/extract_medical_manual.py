"""Extract the reviewed medical operations manual fixture without redrawing images."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pdfplumber
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'Samples/操作手册/医疗影像运维管理系统V1.0 操作手册.pdf'
OUTPUT = ROOT / 'frontend/test-assets/medical-manual'

# Reviewed against PDF pages 3-16; keys are Poppler image occurrence numbers.
# Occurrence 7 is the soft mask of image 6, not another screenshot.
SECTIONS = [
    ('2', [(0, '数据申请列表'), (1, '数据申请审核详情'), (2, '审核通过列表'), (3, '审核结果详情')]),
    ('3.1', [(4, '机构列表'), (5, '部门科室管理'), (6, '部门科室及管理员编辑')]),
    ('3.2', [(8, '字典列表'), (9, '字典键值列表'), (10, '新增字典键值'), (11, '编辑字典键值'), (12, '删除字典键值')]),
    ('3.3', [(13, '用户列表'), (14, '新增用户'), (15, '编辑用户'), (16, '用户更多操作'), (17, '用户角色授权')]),
    ('3.4', [(18, '角色列表'), (19, '新增角色'), (20, '编辑角色')]),
    ('3.5', [(21, '菜单列表'), (22, '新增菜单'), (23, '编辑菜单')]),
    ('3.6', [(24, '操作记录列表')]),
    ('4.1', [(25, '标签列表'), (26, '新增标签'), (27, '编辑标签')]),
    ('4.2', [(28, '标签模板列表'), (29, '新增标签模板')]),
    ('4.3', [(30, '标注工具列表'), (31, '新增标注工具'), (32, '标注工具授权')]),
    ('5', [(33, '标注规则学习情况列表'), (34, '新增标注规则'), (35, '下载学习记录上传模板'), (36, '学习记录表格模板'), (37, '标注规则详情')]),
]


def extract(poppler_bin):
    def run(tool, *args):
        executable = str(Path(poppler_bin) / tool) if poppler_bin else tool
        return subprocess.check_output([executable, *map(str, args)], text=True)

    inventory = []
    for line in run('pdfimages', '-list', SOURCE).splitlines():
        fields = line.split()
        if fields and fields[0].isdigit():
            inventory.append(dict(page=int(fields[0]), index=int(fields[1]), kind=fields[2],
                                  width=int(fields[3]), height=int(fields[4]), objectId=int(fields[10])))
    expected = {index for _, shots in SECTIONS for index, _ in shots}
    actual = {item['index'] for item in inventory if item['kind'] == 'image'}
    if expected != actual:
        raise ValueError('Source image inventory changed; review screenshot mapping before extraction')

    headings, pages = [], []
    with pdfplumber.open(SOURCE) as pdf:
        page_count = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages[2:], start=3):
            body = page.crop((0, 55, page.width, 770)).extract_text() or ''
            pages.append({'page': page_number, 'text': body})
            for line in body.splitlines():
                match = re.fullmatch(r'(\d+(?:\.\d+)*)\.\s*(\S.*)', line.strip())
                if match:
                    number, title = match.groups()
                    headings.append({'number': number, 'title': title, 'page': page_number,
                                     'sourceLevel': number.count('.') + 1,
                                     'type': 'system' if number == '1' else 'page' if '.' in number else 'module',
                                     'parent': None if number == '1' else number.split('.')[0] if '.' in number else '1'})
    assert len(headings) == 14 and len(actual) == 37
    assert {section for section, _ in SECTIONS} <= {h['number'] for h in headings}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    screenshots = []
    metadata = {item['index']: item for item in inventory}
    with tempfile.TemporaryDirectory() as temp:
        prefix = Path(temp) / 'shot'
        run('pdfimages', '-j', SOURCE, prefix)
        for section, shots in SECTIONS:
            for index, title in shots:
                filename = f'shot-{index:03d}.jpg'
                source = Path(temp) / filename
                with Image.open(source) as im:
                    assert im.size == (metadata[index]['width'], metadata[index]['height'])
                shutil.copyfile(source, OUTPUT / filename)
                screenshots.append({**metadata[index], 'title': title, 'section': section, 'file': filename,
                                    'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    # Remove only the earlier extraction's mask, mistakenly converted to a JPEG.
    (OUTPUT / 'shot-007.jpg').unlink(missing_ok=True)
    shutil.copyfile(SOURCE, OUTPUT / 'source.pdf')
    manifest = {
        'id': 'medical-manual-v1', 'title': '医疗影像运维管理系统', 'version': 'V1.0',
        'source': {'path': str(SOURCE.relative_to(ROOT)), 'file': 'source.pdf', 'pages': page_count,
                   'sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest()},
        'mapping': '原文1为系统，2至5为模块，3.x与4.x为页面。保留原编号与页码，不添加原文中不存在的页面标题。截图名称为人工核对的界面说明。',
        'excludedObjects': [item for item in inventory if item['kind'] != 'image'],
        'headings': headings, 'screenshots': screenshots, 'sourceText': pages,
    }
    (OUTPUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# 医疗影像运维管理系统 V1.0 原始目录与截图', '', manifest['mapping'], '',
             '来源：' + manifest['source']['path'], '', '| 原编号 | 标题 | 原文级别 | 画布类型 | 起始页 | 截图数 |',
             '| --- | --- | --- | --- | --- | --- |']
    for heading in headings:
        count = sum(shot['section'] == heading['number'] for shot in screenshots)
        lines.append(f"| {heading['number']} | {heading['title']} | {heading['sourceLevel']} | {heading['type']} | {heading['page']} | {count} |")
    lines.extend(['', '## 截图清单', '', '| 文件 | 界面 | 原文标题 | PDF 页码 |', '| --- | --- | --- | --- |'])
    for shot in screenshots:
        lines.append(f"| [{shot['file']}]({shot['file']}) | {shot['title']} | {shot['section']} | {shot['page']} |")
    lines.extend(['', '共 14 个标题、37 张截图。图像对象 7 是透明蒙版，已排除。', ''])
    (OUTPUT / 'outline.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'Extracted {len(headings)} headings and {len(screenshots)} screenshots to {OUTPUT}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--poppler-bin', default='', help='Directory containing pdfimages')
    extract(parser.parse_args().poppler_bin)
