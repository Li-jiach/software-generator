import base64
import io
import unittest

from docx import Document
from PIL import Image

from export_manual import DEFAULT_TEMPLATE, add_component


class ScreenshotExportTests(unittest.TestCase):
    def test_components_keep_introductions_and_hierarchy_without_legacy_operations(self):
        document = Document()
        nodes = [{'id': kind, 'name': kind, 'type': kind} for kind in ('system', 'module', 'page')]
        generated = {'nodes': {node['id']: {'contentSummary': node['type'] + '组件介绍', 'operation': '旧操作介绍'} for node in nodes}}
        children = {'system': [nodes[1]], 'module': [nodes[2]]}
        add_component(document, nodes[0], generated, children, 1, set())
        self.assertEqual([p.text for p in document.paragraphs], ['system', 'system组件介绍', 'module', 'module组件介绍', 'page', 'page组件介绍'])
        self.assertEqual([p.style.name for p in document.paragraphs[::2]], ['Heading 1', 'Heading 2', 'Heading 3'])

    def test_operations_follow_title_and_precede_image_without_placeholder(self):
        raw = io.BytesIO()
        Image.new('RGB', (2, 2)).save(raw, format='PNG')
        image = 'data:image/png;base64,' + base64.b64encode(raw.getvalue()).decode()
        operation = '1. 点击“查询”按钮，查询列表。\n2. 点击“重置”按钮，清空条件。'
        for node_type in ('screenshot', 'screenshot-group'):
            for legacy in (False, True):
                with self.subTest(node_type=node_type, legacy=legacy):
                    document = Document(DEFAULT_TEMPLATE)
                    count = len(document.paragraphs)
                    node = {'id': 'shot', 'type': node_type, 'image': image, 'screenshots': [{'image': image}]}
                    generated = {'screenshots': {'shot': {'title': '记录查询', 'contentSummary': '概述', 'operation': '截图内容：【' + operation + '】' if legacy else operation}}}
                    add_component(document, node, generated, {}, 1, set())
                    output = io.BytesIO()
                    document.save(output)
                    output.seek(0)
                    exported = Document(output)
                    paragraphs = exported.paragraphs[count:]
                    self.assertEqual(paragraphs[0].text, '记录查询')
                    self.assertEqual(paragraphs[1].text, operation)
                    self.assertEqual(len(exported.inline_shapes), len(document.inline_shapes))
                    self.assertTrue(paragraphs[2]._p.xpath('.//w:drawing'))
                    self.assertFalse(any('截图内容' in p.text for p in paragraphs))


if __name__ == '__main__':
    unittest.main()
