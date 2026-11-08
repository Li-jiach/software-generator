import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from main import optimize, parse_optimized_text, parse_pair, generate_component, generate_full, generate_restructured


class ComponentIntroTests(unittest.IsolatedAsyncioTestCase):
    config = {'endpoint': 'http://example.com/v1', 'model': 'test'}
    nodes = [{'id': kind, 'type': kind, 'name': kind} for kind in ('system', 'module', 'page')]

    async def test_component_requires_only_introduction_and_discards_legacy_operation(self):
        for node in self.nodes:
            for extra in ('', '\n操作介绍：旧操作介绍'):
                with self.subTest(kind=node['type'], extra=extra):
                    with patch('main.call_model', new_callable=AsyncMock, return_value='内容简介：组件的用途和功能范围。' + extra) as model:
                        result = await generate_component({'node': node, 'settings': self.config})
                    self.assertEqual(result['contentSummary'], '组件的用途和功能范围。')
                    self.assertNotIn('operation', result)
                    self.assertIn('不生成 operation 或操作介绍', model.call_args.args[0])

    async def test_parent_prompt_uses_child_summary_without_screenshot_operations(self):
        for node in self.nodes:
            with self.subTest(kind=node['type']):
                with patch('main.call_model', new_callable=AsyncMock, return_value='标题：组件\n内容简介：组件介绍') as model:
                    await generate_component({'node': node, 'settings': self.config, 'children': [
                        {'name': '业务界面', 'generated': {'contentSummary': '支持业务记录查询', 'operation': '不应传入的点击操作详情'}}
                    ]})
                prompt = model.call_args.args[0]
                self.assertIn('支持业务记录查询', prompt)
                self.assertNotIn('不应传入的点击操作详情', prompt)

    async def test_full_generation_accepts_introduction_only_for_every_component_type(self):
        response = {'nodes': {node['id']: {'contentSummary': '组件介绍'} for node in self.nodes}, 'screenshots': {}}
        response['nodes']['module']['operation'] = '旧操作介绍'
        with patch('main.call_model', new_callable=AsyncMock, return_value=json.dumps(response)):
            result = await generate_full({'nodes': self.nodes, 'settings': self.config})
        for node in self.nodes:
            self.assertEqual(result['nodes'][node['id']]['contentSummary'], '组件介绍')
            self.assertNotIn('operation', result['nodes'][node['id']])

    async def test_restructure_does_not_restore_or_send_legacy_operations(self):
        source = {'nodes': {node['id']: {'title': node['name'], 'contentSummary': '组件介绍', 'operation': '旧操作介绍'} for node in self.nodes}, 'screenshots': {}}
        for config in ({}, self.config):
            with self.subTest(configured=bool(config)):
                with patch('main.call_model', new_callable=AsyncMock, return_value=json.dumps(source)) as model:
                    result = await generate_restructured({'nodes': self.nodes, 'generated': source, 'settings': config})
                self.assertEqual(result['nodes']['system']['contentSummary'], '组件介绍')
                for node in self.nodes:
                    self.assertNotIn('operation', result['nodes'][node['id']])
                self.assertEqual(result['nodes']['module']['contentSummary'], '')
                self.assertEqual(result['nodes']['page']['contentSummary'], '')
                if config:
                    self.assertNotIn('旧操作介绍', model.call_args.args[0])

    async def test_restructure_removes_repeated_component_sentences_in_manual_order(self):
        nodes = [
            {'id': 'system', 'type': 'system', 'name': '系统', 'x': 0, 'y': 0},
            {'id': 'module', 'type': 'module', 'name': '模块', 'x': 0, 'y': 1},
            {'id': 'page', 'type': 'page', 'name': '页面', 'x': 0, 'y': 2},
        ]
        source = {'nodes': {
            'system': {'title': '系统', 'contentSummary': '系统用于统一管理业务数据。'},
            'module': {'title': '模块', 'contentSummary': '系统用于统一管理业务数据。模块负责审核申请。'},
            'page': {'title': '页面', 'contentSummary': '模块负责审核申请。页面展示待审记录。'},
        }, 'screenshots': {}}
        result = await generate_restructured({'nodes': nodes, 'generated': source, 'settings': {}, 'tree': [
            {'id': 'system', 'children': [{'id': 'module', 'children': [{'id': 'page', 'children': []}]}]}
        ]})
        self.assertEqual(result['nodes']['system']['contentSummary'], '系统用于统一管理业务数据。')
        self.assertEqual(result['nodes']['module']['contentSummary'], '模块负责审核申请。')
        self.assertEqual(result['nodes']['page']['contentSummary'], '页面展示待审记录。')


class ScreenshotOperationTests(unittest.IsolatedAsyncioTestCase):
    operation = '记录列表展示记录名称和状态，供用户查看查询结果。\n1. 点击“查询”按钮，按已填写的条件查询列表。\n2. 点击“重置”按钮，清空查询条件。'
    config = {'endpoint': 'http://example.com/v1', 'model': 'test'}

    def test_multiline_operations_are_preserved(self):
        pair = parse_pair('内容简介：记录查询界面\n操作说明：\n' + self.operation)
        self.assertEqual(pair['operation'], self.operation)
        self.assertEqual(pair['contentSummary'], '记录查询界面')

    async def test_component_preserves_operations_instead_of_summary(self):
        with patch('main.call_model', new_callable=AsyncMock,
                   return_value='内容简介：记录查询界面\n操作介绍：截图内容：【' + self.operation + '】') as model:
            result = await generate_component({'node': {'id': 'shot', 'type': 'screenshot', 'image': 'data:image/png;base64,one'}, 'settings': self.config})
        self.assertEqual(result['operation'], self.operation)
        prompt = model.call_args.args[0]
        self.assertIn('详细表述该截图中展示的功能', prompt)
        self.assertIn('统计指标、图表、列表及其列、表单字段', prompt)
        self.assertIn('所有可辨认的按钮', prompt)

    async def test_component_generates_screenshot_title_and_preserves_user_title(self):
        for name, expected in [('截图 1', '记录查询'), ('用户指定名称', '用户指定名称')]:
            with self.subTest(name=name):
                with patch('main.call_model', new_callable=AsyncMock, return_value='标题：记录查询\n内容简介：记录查询界面\n操作说明：' + self.operation):
                    result = await generate_component({'node': {'id': 'shot', 'type': 'screenshot', 'name': name}, 'settings': self.config})
                self.assertEqual(result['title'], expected)
                self.assertEqual(result['operation'], self.operation)

    async def test_full_generation_receives_each_screenshot_and_keeps_operations(self):
        nodes = [{'id': 'shot-2', 'type': 'screenshot', 'image': 'data:image/png;base64,two'},
                 {'id': 'shot-1', 'type': 'screenshot', 'image': 'data:image/png;base64,one'}]
        response = {'nodes': {}, 'screenshots': {node['id']: {'title': '记录查询', 'contentSummary': '记录查询界面', 'operation': self.operation} for node in nodes}}
        with patch('main.call_model', new_callable=AsyncMock, return_value=json.dumps(response)) as model:
            result = await generate_full({'nodes': nodes, 'tree': nodes, 'settings': self.config})
        prompt, _, images = model.call_args.args
        self.assertEqual(images, [node['image'] for node in nodes])
        self.assertIn('["shot-2", "shot-1"]', prompt)
        self.assertIn('详细表述该截图中展示的功能', prompt)
        self.assertEqual(result['screenshots']['shot-1']['operation'], self.operation)

    async def test_restructure_keeps_button_details_and_cleans_legacy_prefix(self):
        source = {'nodes': {}, 'screenshots': {'shot': {'title': '记录查询', 'contentSummary': '记录查询界面', 'operation': self.operation}}}
        response = {'nodes': {}, 'screenshots': {'shot': {**source['screenshots']['shot'], 'operation': '截图内容：【' + self.operation + '】'}}}
        with patch('main.call_model', new_callable=AsyncMock, return_value=json.dumps(response)) as model:
            result = await generate_restructured({'nodes': [{'id': 'shot', 'type': 'screenshot'}], 'generated': source, 'settings': self.config})
        self.assertIn('截图项只能保留 title 和 operation', model.call_args.args[0])
        self.assertEqual(result['screenshots']['shot']['operation'], self.operation)
        self.assertNotIn('contentSummary', result['screenshots']['shot'])


class OptimizeTests(unittest.IsolatedAsyncioTestCase):
    async def test_screenshot_chain_uses_all_images_without_node_title(self):
        images = ['data:image/png;base64,first', 'data:image/png;base64,second']
        with patch('main.call_model', new_callable=AsyncMock,
                   return_value='内容简介：业务界面\n操作介绍：完成操作') as model:
            result = await generate_component({
                'node': {'id': 'head', 'type': 'screenshot', 'name': '截图 999', 'images': images},
                'settings': {'endpoint': 'http://example.com/v1', 'model': 'test'}
            })
        prompt, _, passed_images = model.call_args.args
        self.assertNotIn('截图 999', prompt)
        self.assertNotIn('组件名称：', prompt)
        self.assertEqual(passed_images, images)
        self.assertEqual(result['id'], 'head')

    def test_extracts_only_optimized_text(self):
        response = '以下是优化结果：\n```json\n{"optimized_text":"提升医疗影像数据管理效率。"}\n```\n已保留原意。'
        self.assertEqual(parse_optimized_text(response), "提升医疗影像数据管理效率。")

    async def test_optimize_returns_only_field_value(self):
        response = '说明：已润色。\n{"optimized_text":"支持医疗影像数据管理与运维。"}\n优化完成。'
        with patch("main.call_model", new_callable=AsyncMock, return_value=response):
            result = await optimize({
                "field": "purpose",
                "text": "管理医疗影像数据",
                "settings": {"endpoint": "http://example.com/v1", "model": "test"},
            })
        self.assertEqual(result["text"], "支持医疗影像数据管理与运维。")

    async def test_unstructured_response_is_rejected(self):
        with patch("main.call_model", new_callable=AsyncMock, return_value="优化结果：支持数据管理。"):
            with self.assertRaises(HTTPException) as error:
                await optimize({
                    "field": "purpose",
                    "text": "管理数据",
                    "settings": {"endpoint": "http://example.com/v1", "model": "test"},
                })
        self.assertEqual(error.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
