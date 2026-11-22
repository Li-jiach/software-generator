"""End-to-end checks against running Java/Python/MySQL, with disposable records only."""
import base64
import json
import io
import zipfile
import uuid
import os
from pathlib import Path
import subprocess
import sys
import threading
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from init_db import ROOT, load_env
import httpx

env = load_env()
BASE = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8080/api")
clients = {}
project_ids = []
user_ids = []
stored_files = []
checks = 0
seen = []
force_vision_rejection = threading.Event()
stall_review = threading.Event()
review_is_stalled = threading.Event()
release_review = threading.Event()
server = None


def expect(condition, description):
    global checks
    assert condition, description
    checks += 1


def request(client, method, path, expected=200, **kwargs):
    r = client.request(method, BASE + path, **kwargs)
    assert r.status_code == expected, f"{method} {path}: HTTP {r.status_code} {r.text[:250]}"
    return r


class Provider(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/fixture':
            self.send_error(404)
            return
        body = FIXTURE.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=UTF-8')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append((self.path, payload))
        content="根据已提供资料，申请材料包括申请表、鉴别材料和权属证明。[1]"
        prompt = payload['messages'][0]['content']
        if prompt.startswith('操作手册任务：'):
            task = prompt.split('：', 1)[1].split('。', 1)[0]
            if task == '后端源码分析' and payload.get('stream'):
                self.close_connection = True
                return
            user_content = payload['messages'][-1]['content']
            if task == '截图核验':
                assert [part['type'] for part in user_content] == ['text', 'image_url']
                image_url = user_content[1]['image_url']['url']
                assert image_url.startswith('data:image/jpeg;base64,')
                jpeg = base64.b64decode(image_url.split(',', 1)[1], validate=True)
                assert jpeg.startswith(b'\xff\xd8') and jpeg.endswith(b'\xff\xd9')
                data = json.loads(user_content[0]['text'])
                if data['target'] == '资料管理' and stall_review.is_set():
                    stall_review.clear()
                    review_is_stalled.set()
                    release_review.wait(timeout=20)
                    self.close_connection = True
                    return
            else:
                data = json.loads(user_content)
            content = json.dumps(manual_response(task, data), ensure_ascii=False)
        elif '每次只返回一个JSON对象' in prompt:
            task=json.loads(payload['messages'][-1]['content'])
            question=task['question']; observations=task['observations']
            if question=='帮我从跨项目附件填写软件简称':
                if not observations: plan={'action':'search_attachments','args':{'query':'附件包.zip'}}
                elif len(observations)==1: plan={'action':'read_attachment','args':{'id':observations[0]['result'][0]['id']}}
                elif len(observations)==2:
                    entry=next(x['name'] for x in observations[1]['result']['entries'] if x['name'].endswith('README.md'))
                    plan={'action':'read_attachment','args':{'id':observations[0]['result'][0]['id'],'entry':entry}}
                else:
                    short_name=observations[-1]['result']['text'].removeprefix('软件简称：')
                    plan={'action':'fill_form','args':{'projectId':task['context']['projectId'],'fields':{'shortName':short_name}}}
                content=json.dumps(plan,ensure_ascii=False)
            elif question=='哪个软著的附件提到了 PrivateEvidence？':
                step = {'action':'search_projects','args':{'query':'PrivateEvidence'}}
                if observations:
                    step={'action':'project_rag','args':{'projectId':observations[0]['result'][0]['id'],'query':'PrivateEvidence'}}
                content=json.dumps(step)
            elif question=='助手代填目标的版本是什么？':
                step={'action':'search_projects','args':{'query':'助手代填目标'}}
                if observations:
                    step={'action':'project_rag','args':{'projectId':observations[0]['result'][0]['id'],'query':'版本'}}
                content=json.dumps(step,ensure_ascii=False)
            elif question=='根据我刚上传的操作手册填写基础信息':
                manual=next(f for f in task['context']['recentAttachments'] if f['name']=='操作手册联调.txt')
                if not observations:
                    plan={'action':'read_attachment','args':{'id':manual['id'],'query':'软件简称'}}
                else:
                    assert any('软件简称：手册示例' in excerpt for excerpt in observations[-1]['result']['excerpts'])
                    plan={'action':'fill_form','args':{'projectId':task['context']['projectId'],'fields':{'shortName':'手册示例'},'missing':'著作权人'}}
                content=json.dumps(plan,ensure_ascii=False)
            elif question=='帮我填写著作权人':
                content=json.dumps({'action':'fill_form','args':{'projectId':task['context']['projectId'],'fields':{'copyrightOwner':'越权修改'}}})
            elif question=='刚才具体修改了什么？':
                writes=[event for event in task['context']['recentOperations'] if event['action']=='fill_form' and event['changes']]
                if writes:
                    event=writes[-1]
                    change=event['changes'][0]
                    assert event['projectId']==task['context']['projectId']
                    assert task['context']['form']['shortName']=='人工修订简称'
                    assert any(log['title']=='保存填报草稿' and '软件简称' in log['detail'] for log in task['context']['recentProjectActivity'])
                    plan={'action':'answer','answer':f"{event['projectName']}：{change['label']}从「{change['before']}」改为「{change['after']}」。"}
                else:
                    plan={'action':'answer','answer':'当前会话没有已保存的修改。'}
                content=json.dumps(plan,ensure_ascii=False)
            elif question=='帮我把刚才查的项目的软件简称改成测试':
                lookup=next(event for event in reversed(task['context']['recentOperations']) if event['action']=='project_rag')
                content=json.dumps({'action':'fill_form','args':{'projectId':lookup['projectId'],'fields':{'shortName':'错误项目'}}})
            elif question=='刚才那个项目的版本呢？':
                lookup=next(event for event in reversed(task['context']['recentOperations']) if event['action']=='project_rag')
                plan={'action':'search_projects','args':{'query':lookup['projectId']}}
                if observations:
                    plan={'action':'project_rag','args':{'projectId':observations[0]['result'][0]['id'],'query':'版本'}}
                content=json.dumps(plan)
            elif question=='帮我把软件简称改成来自跨项目附件的简称':
                content=json.dumps({'action':'fill_form','args':{'projectId':task['context']['projectId'],'fields':{'shortName':'来自跨项目附件的简称'}}})

            elif question=='这个项目的填写和审核状态怎么样？':
                content=json.dumps({'action':'status'})
            else:
                content=json.dumps({'action':'knowledge','args':{'query':'源程序每页行数'}})
        if payload.get('stream'):
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            if prompt.startswith('操作手册任务：目录文件分类。'):
                reasoning = json.dumps({'choices': [{'delta': {'reasoning_content': 'PRIVATE_MODEL_REASONING'}}]})
                self.wfile.write(('data: '+reasoning+'\n\n').encode())
            for part in (content[:8],content[8:]):
                event=json.dumps({'choices':[{'delta':{'content':part},'finish_reason':None}]},ensure_ascii=False)
                self.wfile.write(('data: '+event+'\n\n').encode())
                self.wfile.flush()
                time.sleep(2.5 if prompt.startswith('操作手册任务：目录文件分类。') and part == content[:8] else .15)
            self.wfile.write(b'data: [DONE]\n\n')
            return
        body = json.dumps({"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 42}}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *_):
        pass


FIXTURE = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>联调测试站点</title>
<style>body{font:22px sans-serif;color:#26344b;background:#f2f6fa;margin:0}nav{background:#1d3457;color:white;padding:32px}
main{margin:68px auto;width:850px;background:white;padding:52px}button{padding:12px 24px}dialog{border:1px solid #8797b0;padding:40px}</style></head>
<body><nav>联调测试站点</nav><main><section id="home"><h1>项目首页</h1><button id="list">资料列表</button></section>
<section id="materials" hidden><h1>资料管理</h1><p>查看项目资料与文件版本。</p><button id="open-detail">查看详情</button></section></main>
<dialog id="detail"><h2>版本详情</h2><p>首次提交 · V1.0</p></dialog>
<script>const byId=id=>document.getElementById(id);byId('list').onclick=()=>{byId('home').hidden=true;byId('materials').hidden=false};
byId('open-detail').onclick=()=>byId('detail').showModal();</script></body></html>'''


def manual_response(task, data):
    navigate = {'role': 'button', 'label': '资料列表'}
    detail = {'role': 'button', 'label': '查看详情'}
    pages = [
        {'id': 'home', 'moduleId': 'workspace', 'title': '项目首页', 'description': '资料入口。',
         'source': '项目样例/index.html', 'steps': [], 'visibleText': '项目首页'},
        {'id': 'unreachable', 'moduleId': 'error', 'title': '服务异常页', 'description': '服务异常时出现。',
         'source': '项目样例/index.html', 'steps': [], 'visibleText': '服务遇到异常'},
        {'id': 'list', 'moduleId': 'files', 'title': '资料管理', 'description': '查看资料和版本。',
         'source': '项目样例/index.html', 'steps': [navigate], 'visibleText': '资料管理'},
    ]
    match task:
        case '目录文件分类':
            assert set(data['directory']) == {'项目样例/index.html','项目样例/backend/ProjectController.java','项目样例/tools/demo.py'}
            return {'frontend': ['项目样例/index.html'], 'backend': ['项目样例/backend/ProjectController.java'],
                    'other': ['项目样例/tools/demo.py']}
        case '前端源码分析':
            assert {entry['path'] for entry in data} == {'项目样例/index.html'}
            assert any('版本详情' in entry['text'] for entry in data)
            return {'facts': 'index.html 含项目首页、资料管理和版本详情对话框。'}
        case '后端源码分析':
            assert {entry['path'] for entry in data} == {'项目样例/backend/ProjectController.java'}
            assert any('ProjectController' in entry['text'] for entry in data)
            return {'facts': 'ProjectController.java 声明了项目控制器。'}
        case '功能目录':
            return {'overview': '用于查阅测试项目的资料与版本。', 'modules': [
                {'id': 'workspace', 'parentId': None, 'title': '项目工作区'},
                {'id': 'files', 'parentId': 'workspace', 'title': '资料管理'},
                {'id': 'error', 'parentId': 'workspace', 'title': '异常界面'},
            ]}
        case '页面与点击路径':
            return {'pages': pages}
        case '主要功能操作':
            return {'operations': [{'id': 'detail', 'pageId': 'list', 'title': '查看版本详情',
                                    'description': '弹窗显示版本信息。', 'instructions': ['点击查看详情。', '读取版本记录。'], 'capture': True},
                                   {'id': 'log-detail', 'pageId': 'list', 'title': '展开日志详情',
                                    'description': '有日志时可展开详情。', 'instructions': ['点击日志条目。'], 'capture': True},
                                   {'id': 'error-detail', 'pageId': 'unreachable', 'title': '异常详情',
                                    'description': '查看异常详情。', 'instructions': ['点击查看错误详情。'], 'capture': True},
                                   {'id': 'rejected-detail', 'pageId': 'list', 'title': '版本详情补充视图',
                                    'description': '查看版本详情。', 'instructions': ['点击查看详情。'], 'capture': True}]}
        case '截图脚本计划':
            targets = [{'operationId': 'detail', 'steps': [detail], 'visibleText': '版本详情'},
                       {'operationId': 'error-detail', 'steps': [{'role': 'button', 'label': '查看错误详情'}],
                        'visibleText': '详细错误'},
                       {'operationId': 'rejected-detail', 'steps': [detail], 'visibleText': '版本详情'}]
            if 'validationFeedback' not in data:
                return {'targets': targets + [{'operationId': 'log-detail', 'steps': [], 'visibleText': '暂无日志'}]}
            assert 'targets.3.steps (too_short)' in data['validationFeedback']
            return {'targets': targets, 'skipped': [{'operationId': 'log-detail', 'cause': 'missing_data',
                                                     'reason': '初始状态没有可展开的日志条目。'}]}
        case '截图核验':
            if (force_vision_rejection.is_set() or data['target'] == '版本详情补充视图'
                    or (data['target'] == '查看版本详情' and data['attempt'] == 1)):
                return {'approved': False, 'reason': '目标区域需要更宽的视口。', 'repair': 'wide'}
            return {'approved': True, 'reason': f"图中可见{data['visibleText']}。"}
        case '手册撰写':
            if 'page' not in data:
                return {'text': '此工作区汇集测试项目的资料与文件版本。'}
            assert data['captured']
            return {'text': {'home': '项目首页提供资料入口。', 'list': '资料管理页展示项目资料和文件版本。'}[data['page']['id']]}
        case '进度摘要':
            return {'text': '当前进度：' + '，'.join(f'{k}：{v}' for k, v in data.items())}
        case _:
            raise AssertionError(task)


def await_job(client, path, status):
    deadline = time.monotonic() + 80
    while time.monotonic() < deadline:
        job = request(client, 'GET', path).json()
        if job['status'] == status:
            return job
        assert job['status'] == 'running', job.get('error') or job['status']
        time.sleep(0.35)
    raise AssertionError(f'expected manual job status {status}')


def chrome_executable():
    path = env.get('MANUAL_CHROMIUM_PATH')
    return {'executable_path': path} if path else {'channel': 'chrome'}


def project_page(browser, client, project_id, route):
    origin = BASE.removesuffix('/api')
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    context.add_cookies([{'name': k, 'value': v, 'url': origin} for k, v in client.cookies.items()])
    context.add_init_script("if (window.top===window) localStorage.setItem('copyright-current-project', "
                            + json.dumps(project_id) + ');')
    page = context.new_page()
    page.goto(origin + '/#' + route)
    return page


def start_manual_from_folder(client, project_id):
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as playwright:
        folder = Path(tmp) / '项目样例'
        for name, data in {'index.html': FIXTURE,
                           'backend/ProjectController.java': 'class ProjectController {}',
                           'tools/demo.py': '# UNSELECTED_SCRIPT',
                           '.env': 'SECRET_SHOULD_NOT_BE_UPLOADED',
                           'node_modules/dependency.js': '// SKIP_DEPENDENCY'}.items():
            file = folder / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(data, encoding='utf-8')
        browser = playwright.chromium.launch(**chrome_executable())
        try:
            page = project_page(browser, client, project_id, 'source')
            page.get_by_role('button', name='选择路径', exact=True).wait_for()
            start = page.get_by_role('button', name='开始分析', exact=True)
            expect(start.is_disabled(), 'analysis requires a source selection')
            project_path = f'/projects/{project_id}'
            source_zip = Path(tmp) / '直接上传.zip'
            with zipfile.ZipFile(source_zip, 'w') as archive:
                archive.writestr('index.html', FIXTURE)
            with page.expect_file_chooser() as chooser:
                page.get_by_role('button', name='使用源码 ZIP').click()
            with page.expect_response(lambda response: response.url.endswith(project_path + '/files')
                                      and response.request.method == 'POST') as upload:
                chooser.value.set_files(source_zip)
            assert upload.value.ok, upload.value.text()
            page.get_by_text('已上传 直接上传.zip', exact=True).wait_for()
            expect(page.get_by_role('combobox', name='项目源码附件').count() == 0
                   and start.is_enabled()
                   and request(client, 'GET', project_path + '/manual-jobs').json()['job'] is None,
                   'ZIP button opens the file chooser and uploads without starting analysis')
            page.get_by_label('选择路径', exact=True).set_input_files(folder)
            page.get_by_text('已选择 项目样例', exact=True).wait_for()
            expect(request(client, 'GET', project_path + '/manual-jobs').json()['job'] is None
                   and all(f['name'] != '项目样例.zip' for f in request(client, 'GET', project_path).json()['files']),
                   'source selection alone neither uploads the folder nor creates a job')
            with page.expect_response(lambda response: response.url.endswith('/manual-jobs/source')
                                      and response.request.method == 'POST') as response:
                start.click()
            result = response.value
            assert result.ok, result.text()
            job = result.json()
            spinner = page.locator('.manual-spinner')
            spinner.wait_for()
            expect(spinner.evaluate("el => getComputedStyle(el).animationName") == 'manual-spin',
                   'manual progress animates while the task runs')
            panels = page.locator('.manual-analysis-panel')
            logs = panels.filter(has=page.get_by_text('解析日志', exact=True))
            results = panels.filter(has=page.get_by_text('分析结果', exact=True))
            expect(panels.count() == 2 and page.locator('.manual-analysis-panel[open]').count() == 0
                   and page.get_by_role('button', name='编辑与送审', exact=True).count() == 0,
                   'results and logs share a collapsed layout and the legacy editor is absent')
            logs.locator('summary').click()
            logs.get_by_text('{"fronte', exact=True).wait_for()
            expect(logs.get_by_text('接收中…', exact=True).is_visible(), 'partial model content appears before the reply completes')
            results.locator('summary').first.click()
            page.get_by_text('前端分析 ·', exact=False).click()
            page.get_by_text('后端分析 ·', exact=False).click()
            page.get_by_text('index.html 含项目首页、资料管理和版本详情对话框。', exact=True).wait_for()
            page.get_by_text('ProjectController.java 声明了项目控制器。', exact=True).wait_for()
            spinner.wait_for(state='hidden')
            expect('PRIVATE_MODEL_REASONING' not in logs.inner_text() and '前端源码分析' in logs.inner_text(),
                   'manual log retains model replies without private reasoning content')
            expect(page.get_by_role('button', name='生成截图计划', exact=True).count() == 0,
                   'screenshot planning has no manual start button')
            expect(page.get_by_text('保存测试站点入口并勾选 Chrome 确认后', exact=False).is_visible()
                   and page.locator('.manual-phases .done').get_by_text('源码分析').is_visible(),
                   'completed source analysis shows what is needed to resume')
            ready = page.get_by_role('checkbox', name='已在 Google Chrome 中打开测试站点', exact=False)
            help_button = page.get_by_role('button', name='查看开发者模式打开方式')
            guide_panel = page.locator('dialog[aria-labelledby="manual-guide-title"]')
            assert not guide_panel.is_visible(), 'tutorial stays hidden before opening'
            help_button.click()
            guide = page.get_by_role('dialog', name='打开 Chrome 开发者工具')
            expect(guide.is_visible() and guide.get_by_text('Windows / Linux', exact=False).is_visible()
                   and guide.get_by_text('macOS', exact=False).is_visible(), 'Chrome DevTools help shows both keyboard shortcuts')
            guide.get_by_role('button', name='关闭', exact=True).click()
            guide_panel.wait_for(state='hidden')
            expect(not ready.is_checked(), 'tutorial dismisses without changing browser confirmation')
            with page.expect_response(lambda response: response.url.endswith('/' + job['id'] + '/generate')
                                      and response.request.method == 'POST') as response:
                ready.check()
            assert response.value.ok, response.value.text()
            active_phase = page.locator('.manual-phases .running')
            active_phase.wait_for()
            expect(active_phase.evaluate("el => getComputedStyle(el, '::after').animationName") == 'manual-phase-sweep',
                   'checking Chrome automatically starts planning and animates its active phase')
            return job
        finally:
            browser.close()


def verify_screenshot_settings_ui(client, project_id, url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**chrome_executable())
        try:
            page = project_page(browser, client, project_id, 'source')
            entry = page.get_by_label('本机测试站点入口')
            entry.fill(url)
            page.get_by_role('button', name='保存站点入口').click()
            page.get_by_text('测试站点入口已保存', exact=True).wait_for()
            page.reload()
            page.wait_for_function("(url) => document.querySelector('#manual-url')?.value === url", arg=url)
            expect(entry.input_value() == url, 'capture entry entered and restored through the frontend')
        finally:
            browser.close()


def verify_assistant_fill_ui(client, project_id, question):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**chrome_executable())
        try:
            page = project_page(browser, client, project_id, 'basic')
            page.get_by_role('button', name='软著助手', exact=True).click()
            page.get_by_role('textbox', name='向软著助手提问').fill(question)
            page.get_by_role('button', name='发送问题').click()
            page.get_by_text('AI 仅供参考', exact=True).wait_for()
            expect(page.get_by_label('软件简称').input_value() == '来自跨项目附件的简称',
                   'the assistant updates and marks the visible form input')
            page.reload()
            page.get_by_role('button', name='软著助手', exact=True).click()
            page.get_by_text('本轮操作', exact=True).last.click()
            expect(page.get_by_text('修改后 · 来自跨项目附件的简称', exact=True).is_visible(),
                   'saved assistant operations remain visible after reload')
        finally:
            browser.close()


def verify_workspace_ui(client, project_id):
    from playwright.sync_api import sync_playwright
    origin = BASE.removesuffix('/api')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**chrome_executable())
        try:
            page = project_page(browser, client, project_id, 'basic')
            actions = page.locator('.form-footer-actions')
            actions.wait_for()
            expect(page.locator('.project-head').count() == 0 and page.get_by_label('当前项目').input_value() == project_id,
                   'workspace removes the duplicated project title while keeping the selector')
            expect(actions.get_by_role('button').count() == 3 and actions.evaluate('el=>getComputedStyle(el).justifyContent') == 'center'
                   and actions.evaluate('el=>el.previousElementSibling.classList.contains("basic-groups")'), 'form actions follow all fields and center')
            page.get_by_role('button', name='检查填写').click()
            toast = page.locator('.toast').first
            toast.wait_for()
            box = toast.bounding_box()
            expect(box['y'] < 80 and abs(box['x'] + box['width'] / 2 - 720) < 5, 'toast appears centered at the top')
            page.goto(origin + '/#source')
            toolbar = page.get_by_role('group', name='手册生成操作')
            toolbar.get_by_role('button', name='下载 Word 手册').wait_for()
            expect(toolbar.get_by_role('link', name='下载截图计划').count() == 0
                   and toolbar.get_by_role('button', name='重置状态').is_visible(),
                   'the Word download appears beside reset without a screenshot-plan download')
            page.set_viewport_size({'width': 390, 'height': 844})
            expect(page.get_by_role('heading', name='解析进程').is_visible() and page.get_by_label('当前项目').is_visible()
                   and page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'manual generation and selector fit a mobile viewport')
        finally:
            browser.close()


def verify_review_ui(admin, project_id):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**chrome_executable())
        try:
            page = project_page(browser, admin, project_id, 'reviews')
            form = page.locator(f'#review-form-{project_id}')
            form.wait_for()
            sections = form.locator('..').locator(':scope > details')
            expect(sections.count() == 4 and form.locator('..').locator(':scope > details[open]').count() == 0,
                   'the four review sections are collapsed on entry')
            form.locator(':scope > summary').click()
            expect(form.get_by_role('button').all_text_contents() == ['通过', '不通过'],
                   'the form has one approval and one rejection action')
            form.get_by_role('button', name='不通过', exact=True).click()
            dialog = page.get_by_role('dialog', name='审核不通过')
            confirm = dialog.get_by_role('button', name='确认不通过')
            expect(confirm.is_disabled(), 'a rejection requires a reason')
            dialog.get_by_label('不通过原因').fill('请补充实际开发目的')
            expect(confirm.is_enabled(), 'entering a reason enables rejection')
            dialog.get_by_role('button', name='取消').click()
            form.locator(':scope > summary').click()
            expect(form.get_attribute('open') is None, 'the review section can be collapsed again')
        finally:
            browser.close()


def verify_official_macro(page, macro, configured, session_failure=None):
    data = {
        'fullName':'测试软件','version':'V2.0','shortName':'测试','rights':'全部权利',
        'devFinish':'2025-06-01','softwareType':'应用软件','copyrightOwner':'测试著作权人',
        'supportSoftware':'PostgreSQL 16，Redis 7','devCPU':'测试型号','devRAM':'16 GB',
        'runCPU':'运行型号','runRAM':'8 GB','languages':'Java,Python'
    }
    portal_html = """<meta charset="utf-8"><body><script>
        const sessionKey = '__fixture_session__';
        const testRetry = sessionKey.endsWith('_False');
        const blockedSession = sessionKey.endsWith('_blocked');
        const rejectedSession = sessionKey.endsWith('_rejected');
        window.getCookie = () => !blockedSession &&
          document.cookie.split('; ').includes(sessionKey+'=verified');
        const pages = {
          application: `
            <section class="fillin_item"><h3>软件全称</h3><input id="name"></section>
            <section class="fillin_item"><h3>版本号</h3><input id="version"></section>
            <section class="fillin_item"><h3>软件简称</h3><input id="short"></section>
            <section class="fillin_item"><h3>权利范围</h3>
             <label><input style="display:none" type="radio" name="rights">部分权利</label>
             <label><input style="display:none" type="radio" name="rights" id="all">全部权利</label>
            </section>`,
          development:`
            <section class="fillin_item"><h3>软件分类</h3><div class="hd-select">
              <div class="box">应用软件</div><div class="dropdown" hidden><div class="hd-option">应用软件</div></div>
            </div></section>
            <section class="fillin_item"><h3>著作权人</h3><table><tr><td>测试著作权人</td></tr></table></section>
            <section class="fillin_item"><h3>开发完成日期</h3><input type="date" id="date"></section>`,
          features:`
            <section class="fillin_item"><h3>开发的硬件环境</h3><textarea id="dev"></textarea></section>
            <section class="fillin_item"><h3>运行的硬件环境</h3><textarea id="run"></textarea></section>
            <section class="fillin_item"><h3>软件运行支撑环境 / 支持软件</h3><textarea id="support"></textarea></section>
            ${['程序鉴别材料','文档鉴别材料','其他相关证明文件'].map(label =>
              '<section class="fillin_item"><h3>'+label+'</h3><div class="hdUpload"><div class="hdUpload-imgBtn hdUpload-item">上传<input type="file" hidden></div></div></section>'
            ).join('')}
            <section class="fillin_item"><h3>编程语言</h3>
             <label><input style="display:none" type="checkbox" id="java">Java</label>
             <label><input style="display:none" type="checkbox" id="python">Python</label>
            </section>`
        };
        function render(stage) {
          history.replaceState(null,'','#/'+stage);
          document.body.innerHTML = pages[stage]+'<div class="fillin_button"><button>下一步</button></div>';
          const next = document.querySelector('.fillin_button button');
          const saved = {};
          if (stage==='application') {
            for (const key of ['name','version','short']) {
              document.querySelector('#'+key).addEventListener('blur',event=>{
                if (event.isTrusted) saved[key]=event.target.value;
                if (key==='version' && !saved.name) sessionStorage.fixtureMissingSoftName='yes';
              });
            }
          }
          if (stage==='development') {
            next.disabled = true;
            setTimeout(()=>{next.disabled=false},900);
            document.querySelector('.hd-select .box').onclick=()=>{
              sessionStorage.fixtureTouchedCategory='yes';
            };
          }
          if (stage==='features' && testRetry) {
            const group = document.querySelector('.hdUpload');
            const card = document.createElement('div');
            card.className = 'hdUpload-item hdUpload-item-imgBox';
            card.innerHTML = '<p class="pdfName">源程序鉴别材料.pdf</p>';
            group.append(card);
            group.querySelector('input').addEventListener('change',()=>{sessionStorage.fixtureReuploaded='yes'});
          }
          next.onclick = () => {
            if (stage==='application') {
              const inputs = [saved.name,saved.version,saved.short];
              if (inputs.join('|')==='测试软件|V2.0|测试' && document.querySelector('#all').checked) render('development');
            }
            if (stage==='development' && document.querySelector('#date').value==='2025-06-01') {
              render('features');
            }
            if (stage==='features' && document.querySelectorAll('.pdfName').length===3) {
              const filenames = [...document.querySelectorAll('.pdfName')].map(node=>node.textContent);
              sessionStorage.fixtureFields = ['#dev','#run','#support'].map(selector=>document.querySelector(selector).value)
                .concat(['#java','#python'].map(selector=>document.querySelector(selector).checked)).join('|');
              history.replaceState(null,'','#/confirm');
              document.body.innerHTML='<div class="material_list"><table><tr><td></td><td><input value="1"></td></tr></table></div><button>确认填报</button>';
              for (const name of filenames) {
                const item = document.createElement('p');
                item.textContent = name;
                document.querySelector('.material_list td').append(item);
              }
              document.querySelector('button').onclick=()=>{history.replaceState(null,'','#/success')};
            }
          };
          for (const input of document.querySelectorAll('input[type=file]')) {
            input.onchange=async ()=>{
              const file=input.files[0];
              if (!file || file.type!=='application/pdf' || !(await file.text()).startsWith('%PDF-')) return;
              const card=document.createElement('div');
              card.className='hdUpload-item';
              card.innerHTML='<i class="hdUpload-item-progressLoop"></i>';
              input.closest('.hdUpload').append(card);
              setTimeout(()=>{
                const name=document.createElement('p');
                name.className='pdfName';
                name.textContent=file.name;
                card.replaceChildren(name);
              },200);
            };
          }
        }
        function renderLogin(root, onVerified) {
          root.innerHTML='<button id="org">机构</button><div id="login"></div>';
          root.querySelector('#org').onclick = () => {
            root.querySelector('#login').innerHTML='<span>管理员</span><span>密码登录</span>'+
              '<input placeholder="请输入账号"><input type="password"><button id="submit">立即登录</button>';
            root.querySelector('#submit').onclick=()=>{
              const [username,password]=root.querySelectorAll('input');
              if (username.value==='fixture-admin' && password.value==='fixture-password') {
                if (testRetry && !sessionStorage[sessionKey+'NetworkError']) {
                  sessionStorage[sessionKey+'NetworkError']='yes';
                  const error = document.createElement('div');
                  error.className='hd-message';
                  error.textContent='网络异常请刷新页面后重试';
                  root.append(error);
                  return;
                }
                root.querySelector('#login').innerHTML='<button id="verify">人工安全验证</button>';
                root.querySelector('#verify').onclick=()=>{
                  document.cookie=sessionKey+'=verified; domain=ccopyright.com.cn; path=/';
                  sessionStorage[sessionKey]=Date.now();
                  onVerified();
                };
              }
            };
          };
        }
        if (location.pathname==='/registration.html') {
          function recordEarlyNavigation() {
            if (sessionStorage[sessionKey] && Date.now()-Number(sessionStorage[sessionKey])<5000)
              sessionStorage[sessionKey+'Early']='yes';
          }
          recordEarlyNavigation();
          document.body.innerHTML='<span>登录</span>'+
            '<main class="register-soft"><div class="link-box"><div class="img-box">R11</div><button id="r11">立即登记</button></div>'+
            '<div class="link-box"><div class="img-box">R21</div><button id="r21">立即登记</button></div></main>';
          let clicks = 0;
          document.querySelector('#r11').onclick=()=>{
            recordEarlyNavigation();
            if (!sessionStorage[sessionKey] || rejectedSession) {
              if (testRetry) {location.href='/login.html';return;}
              const modal = document.createElement('div');
              modal.className='lg_hd_dialog_warp';
              modal.innerHTML='<div class="hd-dialog"></div>';
              document.body.append(modal);
              renderLogin(modal.querySelector('.hd-dialog'),()=>modal.remove());
              return;
            }
            if (++clicks===1 && testRetry) return;
            location.href='/r11.html#/identity';
          };
        } else if(location.pathname==='/login.html') {
          renderLogin(document.body,()=>{location.href='/account.html'});
        } else if(location.pathname==='/r11.html') {
          document.body.innerHTML='<h2>我是申请人</h2>';
          document.querySelector('h2').onclick=()=>{
            history.replaceState(null,'','#/application');
            document.body.innerHTML='<p>表单加载中</p>';
            setTimeout(()=>render('application'),250);
          };
        }
      </script>""".replace('__fixture_session__', f'fixture_signed_in_{session_failure or configured}')
    def serve_portal(route):
        route.fulfill(content_type='text/html',body=portal_html)
    def serve_payload(route):
        redeemed = route.fetch()
        assert redeemed.ok, 'the actual launch endpoint validates the ticket'
        account = {'username':'fixture-admin','password':'fixture-password'} if configured else {}
        route.fulfill(json={**redeemed.json(),'form':data,'login':account})

    page.context.route('https://register.ccopyright.com.cn/**',serve_portal)
    page.context.route('**/official-application/consume',serve_payload)
    popup = None
    try:
        setup = next(cmd['Target'] for cmd in macro['Commands'] if cmd['Value']=='officialStarted')
        tick = next(cmd['Target'] for cmd in macro['Commands'] if cmd['Command']=='executeScript' and cmd['Value']=='officialStep')
        expect('fixture-password' not in str(macro), 'the browser macro stores no credentials')
        popup_start = next(cmd['Target'] for cmd in macro['Commands'] if cmd['Value']=='officialPopupStarted')
        page.evaluate('code => new Function(code)()',setup)
        opener = page.get_by_role('button', name='打开申报窗口')
        opener.wait_for()
        expect(len(page.context.pages) == 1, 'approval finishes before any popup can take focus')
        with page.expect_popup() as opened:
            opener.click()
        popup = opened.value
        popup.wait_for_load_state('domcontentloaded')
        target = next(cmd['Target'] for cmd in macro['Commands'] if cmd['Target'].startswith('title=官网申报窗口'))
        expect(popup.title() == target.removeprefix('title='),
               'Ui.Vision selects the exact window opened for this run')
        popup.evaluate('code => new Function(code)()',popup_start)
        popup.wait_for_url('https://register.ccopyright.com.cn/login.html')
        manual = False
        entered_credentials = False
        reloaded_login = False
        waited_after_login = False
        clicked_pages = set()
        for _ in range(360):
            if '等待 5 秒' in page.locator('#official-live [role=status]').inner_text():
                waited_after_login = True
            try:
                popup.evaluate('code => new Function(code)()',tick)
            except Exception as error:
                if 'Execution context was destroyed' not in str(error):
                    raise
            retry_login = page.get_by_role('button',name='重新加载官网登录页')
            if not configured and not reloaded_login and retry_login.is_visible():
                retry_login.click()
                reloaded_login = True
                entered_credentials = False
            if not configured and not entered_credentials and popup.locator('#org').is_visible():
                pending = page.locator('#official-live [role=status]')
                if '登录' in pending.inner_text() and '官网' in pending.inner_text():
                    popup.locator('#org').click()
                    popup.get_by_placeholder('请输入账号').fill('fixture-admin')
                    popup.locator('input[type=password]').fill('fixture-password')
                    popup.locator('#submit').click()
                    entered_credentials = True
            if popup.locator('#verify').is_visible():
                expect('安全验证' in page.locator('#official-live [role=status]').inner_text(),
                       'the workbench keeps the actual verification controls interactive')
                popup.get_by_role('button',name='人工安全验证').click()
                manual = True
            status = page.locator('#official-live [role=status]').inner_text()
            stage = popup.url.rsplit('/', 1)[-1]
            if stage == 'identity' and '请在官网选择办理身份' in status:
                popup.get_by_role('heading', name='我是申请人').click()
            elif '手动点击「下一步」' in status and stage in {'application','development','features'} and stage not in clicked_pages:
                for _ in range(3):
                    popup.evaluate('code => new Function(code)()',tick)
                expect(popup.url.endswith('#/'+stage), f'the macro waits for the operator on {stage}')
                popup.get_by_role('button',name='下一步',exact=True).click()
                clicked_pages.add(stage)
            if page.locator('#official-live').get_attribute('data-official-state')=='done':
                break
            page.wait_for_timeout(70)
        status = page.locator('#official-live [role=status]').inner_text()
        if session_failure:
            message = '未读取到登录会话' if session_failure == 'blocked' else '再次要求登录'
            expect(manual and waited_after_login and message in status and
                   page.locator('#official-live').get_attribute('data-official-state') == 'done',
                   'the macro stops when the official login session is missing or rejected')
            if session_failure == 'blocked':
                expect(popup.url.endswith('/account.html'),
                       'an account page without a cookie does not trigger navigation to R11')
            recovery = page.get_by_role('link', name='在新标签页打开官网')
            expect(recovery.get_attribute('href') == 'https://register.ccopyright.com.cn/login.html' and
                   recovery.get_attribute('target') == '_blank',
                   'the recovery link opens the official login as a top-level page')
            return
        expect((configured or entered_credentials) and manual and '信息和附件已填至官网确认页' in status,
               f'the macro resumes after login across all three R11 stages (configured={configured}, status={status})')
        expect(configured or reloaded_login, 'an official login network warning can be retried inside the same workbench run')
        expect(waited_after_login and popup.evaluate(
            "() => !sessionStorage.fixture_signed_in_TrueEarly && !sessionStorage.fixture_signed_in_FalseEarly"),
            'the macro waits five seconds after verification before reopening registration or clicking R11')
        expect(popup.evaluate('sessionStorage.fixtureFields') ==
               'CPU 测试型号，内存 16 GB|CPU 运行型号，内存 8 GB|PostgreSQL 16，Redis 7|true|true',
               'the macro fills hardware and language fields before uploading')
        expect(popup.evaluate('!sessionStorage.fixtureMissingSoftName'),
               'the real blur sequence saves the software name before the version validation')
        expect(popup.evaluate('!sessionStorage.fixtureTouchedCategory'),
               'an existing software category is preserved while the macro waits for the Next button')
        expect(not popup.evaluate('sessionStorage.fixtureReuploaded'),
               'an existing uploaded card is recognized without selecting the PDF again')
        expect(popup.url.endswith('#/confirm') and popup.get_by_role('button',name='确认填报').is_enabled() and
               popup.locator('.material_list td p').all_text_contents() ==
               ['源程序鉴别材料.pdf','操作手册.pdf','权属证明.pdf'],
               'the macro uploads approved PDFs and stops before pressing confirmation')
        expect(popup.evaluate('code => new Function(code)()',tick) == 'done',
               'the macro receives its stop signal in the official window')

    finally:
        if popup is not None:
            popup.close()
        page.context.unroute('https://register.ccopyright.com.cn/**',serve_portal)
        page.context.unroute('**/official-application/consume',serve_payload)


def verify_application_ui(client, admin, project_id):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**chrome_executable())
        try:
            page = project_page(browser, client, project_id, 'rpa')
            page.get_by_role('heading', name='实时申报状态').wait_for()
            expect(page.get_by_role('heading', name='申报流程与执行记录').count()==0,
                   'the live status replaces the execution timeline on the application page')
            expect(page.locator('.sidebar .brand').inner_text().strip() == '', 'sidebar brand title is removed')
            page.evaluate("""
                () => {
                    document.documentElement.setAttribute('data-kantu', '1');
                    window.addEventListener('kantuSaveAndRunMacro', (event) => {
                        window.launchMacro = event.detail.json;
                        window.dispatchEvent(new CustomEvent('kantuInvokeSuccess'));
                    });
                }
            """)
            initial_url = page.url
            for attempt, failure in enumerate((None, None, 'blocked', 'rejected')):
                page.evaluate('window.launchMacro = null')
                page.get_by_role('button', name='启动申报', exact=True).click()
                page.wait_for_function('window.launchMacro !== null')
                expect(page.url == initial_url and len(page.context.pages)==1 and
                       page.locator('#official-live iframe').count()==0,
                       'starting requests Ui.Vision approval in the current tab before opening the official window')
                macro = page.evaluate('window.launchMacro')
                select_window, wait_for_panel = macro['Commands'][:2]
                expect(select_window['Target'] == 'title=' + page.title()
                       and page.locator(wait_for_panel['Target'].removeprefix('css=')).count()==1,
                       'Ui.Vision targets the active workbench tab and its launch panel')
                expect(macro['Name'] == 'Copyright_R11_Fill' and any(cmd['Command']=='selectWindow' and cmd['Target'].startswith('title=官网申报窗口')
                                                                          for cmd in macro['Commands'])
                       and '联调验证项目' not in str(macro), 'application button launches a reusable macro without saved form data')
                verify_official_macro(page, macro, configured=attempt != 1, session_failure=failure)
            page.set_viewport_size({'width': 390, 'height': 844})
            expect(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'application preview fits a mobile viewport')
            expect(page.get_by_role('heading', name='申报页面', exact=True).count() == 0
                   and page.get_by_role('heading', name='人工合规核验', exact=True).count() == 0,
                   'obsolete application panels are removed')
            account = project_page(browser, admin, project_id, 'official-account')
            account.get_by_label('机构管理员账号').wait_for()
            expect(account.get_by_label('机构管理员账号').is_visible() and not account.get_by_label('官网密码').input_value(),
                   'the admin settings do not echo a saved password')
            expect(page.get_by_role('button', name='官网账号', exact=True).count() == 0,
                   'the account settings are hidden for contributors')
            users = project_page(browser, admin, project_id, 'users')
            users.get_by_role('button', name='注册账号').click()
            expect(users.locator('#account-department option').all_text_contents()[1:] ==
                   ['研发中心', '健康医疗大数据中心', '人才评价与发展中心', '培训中心'],
                   'account department dropdown has the four requested options')
        finally:
            browser.close()


try:
    anon = httpx.Client(timeout=130, trust_env=False)
    request(anon, "GET", "/projects", expected=401)
    for username in ("admin", "adminDept", "research"):
        client = httpx.Client(timeout=130, trust_env=False)
        request(client, "POST", "/auth/login", json={"username": username, "password": env["BOOTSTRAP_PASSWORD"]})
        expect(request(client, "GET", "/auth/me").json()["username"] == username, f"{username} authenticated")
        clients[username] = client
    admin, office, research = (clients[x] for x in ("admin", "adminDept", "research"))
    request(research, "PUT", "/assistant/config", expected=403, json={"model": "spoof"})
    p = request(admin, "POST", "/projects", json={"name": "联调验证项目（临时）", "version": "V1.0", "dept": "研发中心", "owner": "集成测试", "description": "自动化验证，结束后仅清除此项目"}).json()
    pid = p["id"]
    project_ids.append(pid)
    expect(request(research, "GET", "/projects/" + pid).status_code == 200, "department project access")
    request(research, "PUT", f"/projects/{pid}/form", expected=403, headers={"X-Role": "admin"}, json={"revision": p["revision"], "fields": {"copyrightOwner": "不允许的越权修改"}})
    request(admin, "PUT", f"/projects/{pid}/form", expected=409, json={"revision": 0, "fields": {"purpose": "old"}})
    invalid = request(office, "PUT", f"/projects/{pid}/form", json={"revision": p["revision"], "fields": {"shortName": "可继续填写"}}).json()
    request(office, "POST", f"/projects/{pid}/form/submit", expected=422, json={"revision": invalid["revision"]})
    p = request(office, "GET", f"/projects/{pid}").json()
    expect(p["formStatus"] == "draft" and p["revision"] == invalid["revision"] and p["form"]["shortName"] == "可继续填写", "failed validation preserves editable draft and revision")
    fields = request(admin, "GET", "/metadata").json()["fields"]
    expect(any(issue['field']=='supportSoftware' for issue in request(
           research, 'POST', f'/projects/{pid}/form/validate').json()),
           'support software is required by the server')
    values = {}
    for f in fields:
        values[f["id"]] = f["opts"][0] if f.get("type") in ("select","multiselect") else "2026-01-01" if f.get("type") == "date" else "1" if f.get("type") == "number" else "验证环境与功能说明"
    values.update(fullName="联调验证项目（临时）", version="V1.0", mainFunction="本系统提供项目登记、分工填报、材料管理、审核核验、进度查询以及知识检索功能，面向研发人员和知识产权管理人员，支持数据记录、附件留存、业务查询、资料归档与工作协同。" * 10)
    p = request(admin, "PUT", f"/projects/{pid}/form", json={"revision": p["revision"], "fields": values}).json()
    expect(not p["validation"], "server-side field validation")
    request(office, "POST", f"/projects/{pid}/form/submit", expected=409, json={"revision": invalid["revision"]})
    p = request(office, "POST", f"/projects/{pid}/form/submit", json={"revision": p["revision"]}).json()
    expect(p["formStatus"] == "submitted", "submit for review")
    verify_review_ui(admin, pid)
    form_review = f"/projects/{pid}/form/review"
    decision = {"revision": p["revision"], "status": "approved"}
    request(research, "POST", form_review, expected=403, json=decision)
    request(admin, "POST", form_review, expected=400, json={**decision, "field": "purpose"})
    request(admin, "POST", form_review, expected=400, json={**decision, "status": "returned", "comment": " "})
    reason = "请补充实际开发目的"
    p = request(admin, "POST", form_review, json={**decision, "status": "returned", "comment": reason}).json()
    expect(p["formStatus"] == "returned" and p["formReviews"]["all"]["comment"] == reason, "form-level rejection records its reason")
    request(admin, "POST", form_review, expected=409, json={**decision, "revision": p["revision"]})
    p = request(research, "PUT", f"/projects/{pid}/form", json={"revision": p["revision"], "fields": {"purpose": "提升科研机构的软件资料管理效率"}}).json()
    expect("all" not in p["formReviews"], "changing the form invalidates its previous review")
    p = request(office, "POST", f"/projects/{pid}/form/submit").json()
    request(admin, "POST", form_review, expected=409, json=decision)
    p = request(admin, "POST", form_review, json={**decision, "revision": p["revision"]}).json()
    expect(p["formStatus"] == "approved" and p["formReviews"]["all"]["status"] == "approved", "form-level approval")
    p = request(research, "PUT", f"/projects/{pid}/form", json={"revision": p["revision"], "fields": {"purpose": "再次修改软件开发目的"}}).json()
    expect(p["formStatus"] == "draft" and "all" not in p["formReviews"], "changing an approved form invalidates approval")
    content = "项目内部资料：隔离测试标记PrivateEvidence。源程序每页不少于50行。".encode()
    one = request(office, "POST", f"/projects/{pid}/files", files={"file": ("填报测试资料.txt", content, "text/plain")}, data={"category": "技术文档"}).json()
    two = request(office, "POST", f"/projects/{pid}/files", files={"file": ("填报测试资料.txt", content + b" v2", "text/plain")}, data={"category": "技术文档"}).json()
    expect(one["version"] == 1 and two["version"] == 2, "attachment versions increment")
    expect(request(office, "GET", f"/projects/{pid}/files/{one['id']}/download").content == content, "original attachment is durable and exact")
    expect("50行" in request(research, "GET", f"/projects/{pid}/files/{one['id']}/text").json()["text"], "text extraction through Python")
    request(research, "POST", f"/projects/{pid}/records", expected=403, json={})
    request(office, "POST", f"/projects/{pid}/records", json={"status": "已受理", "referenceNo": "TEST-ONLY-001", "occurredAt": "2026-01-01T12:00:42", "note": "联调测试记录，非官网回执", "evidenceId": one["id"]})
    p = request(admin, "GET", f"/projects/{pid}").json()
    expect(len(p["records"]) == 1 and p["records"][0]["referenceNo"] == "TEST-ONLY-001", "application records retain evidence")
    record=p['records'][0]
    request(research,'PUT',f"/projects/{pid}/records/{record['id']}",expected=403,json=record)
    request(research,'DELETE',f"/projects/{pid}/records/{record['id']}",expected=403)
    request(office,'PUT',f"/projects/{pid}/records/{record['id']}",json={**record,'note':'编辑后的真实测试记录'})
    expect(request(admin,'GET',f'/projects/{pid}').json()['records'][0]['note']=='编辑后的真实测试记录','record update persisted')
    request(office,'DELETE',f"/projects/{pid}/records/{record['id']}")
    expect(not request(admin,'GET',f'/projects/{pid}').json()['records'],'record deletion persisted')
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED) as z:
        z.writestr('源代码/README.md','软件简称：来自跨项目附件的简称')
        z.writestr('large.bin',b'x'*(21*1024*1024))
    zipped=request(office,'POST',f'/projects/{pid}/files',files={'file':('附件包.zip',archive.getvalue(),'application/zip')}).json()
    request(office,'POST',f'/projects/{pid}/files',expected=400,files={'file':('附件包.txt',archive.getvalue(),'text/plain')})
    expect(request(admin,'GET',f"/projects/{pid}/files/{zipped['id']}/download").content==archive.getvalue(),'ZIP over20MB streams intact')
    manual=request(office,'PUT',f'/projects/{pid}/manual',json={'revision':0,'chapters':[{'id':'ch1','title':'测试章节','body':'实际操作说明','verified':False}]}).json()
    request(office,'POST',f'/projects/{pid}/manual/submit',expected=422,json={'revision':manual['revision']})
    manual=request(office,'PUT',f'/projects/{pid}/manual',json={'revision':manual['revision'],'chapters':[{'id':'ch1','title':'测试章节','body':'实际操作说明','verified':True}]}).json()
    manual=request(office,'POST',f'/projects/{pid}/manual/submit',json={'revision':manual['revision']}).json()
    expect(any(n['projectId']==pid and n['kind']=='manual' for n in request(admin,'GET','/notifications').json()),'manual submission notifies administrator')
    expect(not any(n['projectId']==pid and n['kind']=='manual' for n in request(office,'GET','/notifications').json()),'pending review is assigned to administrator')
    request(research,'POST',f'/projects/{pid}/manual/review',expected=403,json={'revision':manual['revision'],'status':'approved'})
    request(office,'PUT',f'/projects/{pid}/manual',expected=409,json={'revision':manual['revision'],'chapters':[]})
    request(admin,'POST',f'/projects/{pid}/manual/review',expected=400,json={'revision':manual['revision'],'status':'returned','comment':' '})
    manual=request(admin,'POST',f'/projects/{pid}/manual/review',json={'revision':manual['revision'],'status':'returned','comment':'补充操作结果'}).json()
    expect(any(n['projectId']==pid and n['kind']=='manual' and n['status']=='returned' for n in request(office,'GET','/notifications').json()),'returned manual is assigned to project contributors')
    manual=request(office,'PUT',f'/projects/{pid}/manual',json={'revision':manual['revision'],'chapters':[{'id':'ch1','title':'测试章节','body':'实际操作说明与结果','verified':True}]}).json()
    manual=request(office,'POST',f'/projects/{pid}/manual/submit',json={'revision':manual['revision']}).json()
    request(admin,'POST',f'/projects/{pid}/manual/review',json={'revision':manual['revision'],'status':'approved'})
    from pypdf import PdfWriter
    pdf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(pdf)
    official_pdf = pdf.getvalue()
    from docx import Document
    official_docx = io.BytesIO()
    word = Document()
    word.add_paragraph("R11 operation manual")
    word.save(official_docx)
    approved_manual = request(office, 'POST', f'/projects/{pid}/files',
                              files={'file': ('操作手册.docx', official_docx.getvalue(),
                                              'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
                              data={'category': '操作手册'}).json()
    material_path = f'/projects/{pid}/application-materials'
    precheck_path = f'/projects/{pid}/application-precheck'
    start_path = f'/projects/{pid}/application-preview/start'
    official_path = f'/projects/{pid}/official-application'
    request(office, 'POST', official_path+'/start', expected=409)
    request(research, 'POST', official_path+'/start', expected=403)
    for method in ('GET', 'PUT'):
        request(office, method, '/admin/official-credentials', expected=403, json={})
    request(office, 'POST', start_path, expected=409)
    request(research, 'POST', start_path, expected=403, headers={'X-Role': 'admin'})
    request(research, 'POST', material_path+'/source/submit', expected=422, json={'attachmentId': zipped['id']})
    for kind, category, filename in [('source', '源程序鉴别材料', '源程序鉴别材料.pdf'), ('ownership', '权属材料', '权属证明.pdf')]:
        artifact = request(research, 'POST', f'/projects/{pid}/files',
                           files={'file': (filename, official_pdf, 'application/pdf')}, data={'category': category}).json()
        review_path = material_path + f'/{kind}/review'
        submit_path = material_path + f'/{kind}/submit'
        submission = request(research, 'POST', submit_path, json={'attachmentId': artifact['id']}).json()
        expect(any(n['projectId']==pid and n['kind']==kind for n in request(admin,'GET','/notifications').json()),
               'material submission sends an administrator notification')
        body = {'reviewId': submission['reviewId'], 'status': 'approved'}
        request(research, 'POST', review_path, expected=403, json=body)
        request(admin, 'POST', review_path, expected=400, json={**body,'status':'returned','comment':' '})
        request(admin, 'POST', review_path, json={**body,'status':'returned','comment':'请重新核对'})
        expect(any(n['projectId']==pid and n['kind']==kind and n['status']=='returned'
                   for n in request(research,'GET','/notifications').json()), 'returned material notifies project contributors')
        retry = request(research, 'POST', submit_path, json={'attachmentId': artifact['id']}).json()
        request(admin, 'POST', review_path, expected=409, json=body)
        request(admin, 'POST', review_path, json={**body,'reviewId':retry['reviewId']})
    request(office, 'POST', start_path, expected=409)
    p = request(office, 'POST', f'/projects/{pid}/form/submit').json()
    request(admin, 'POST', form_review, json={'revision': p['revision'], 'status': 'approved'})
    expect(all(check['status']=='approved' for check in request(office,'GET',precheck_path).json()['checks']),
           'the live precheck verifies all four approvals')
    expect(request(office,'POST',start_path).json()=={'mode':'preview'}, 'approved materials start the preview')
    ticket = request(office,'POST',official_path+'/start').json()
    request(admin,'POST',official_path+'/consume',expected=409,json=ticket)
    launch = request(office,'POST',official_path+'/consume',json=ticket)
    expect('no-store' in launch.headers.get('Cache-Control', '') and
           launch.json()['form']['fullName'] == values['fullName'] and launch.json()['login'] == {} and
           launch.json()['materials']['manual']['id'] == 'chapters' and
           set(launch.json()['materials']) == {'manual','source','ownership'},
           'one-time launch uses approved data and only administrators may use shared credentials')
    request(office,'POST',official_path+'/consume',expected=409,json=ticket)
    approved = launch.json()['materials']
    for kind, item in approved.items():
        pdf_path = official_path + f"/materials/{kind}/{item['id']}/pdf"
        params = {'sha256': item['sha256']}
        request(research, 'GET', pdf_path, expected=403, params=params)
        request(office, 'GET', pdf_path, expected=409, params={'sha256': '0'*64})
        result = request(office, 'GET', pdf_path, params=params)
        expect(result.headers['content-type'] == 'application/pdf' and result.content.startswith(b'%PDF-'),
               f'approved {kind} material is prepared as a PDF')
    verify_application_ui(office, admin, pid)
    manual = request(office,'POST',f'/projects/{pid}/manual/submit',
                     json={'revision':manual['revision']+1,'attachmentId':approved_manual['id']}).json()
    request(admin,'POST',f'/projects/{pid}/manual/review',json={'revision':manual['revision'],'status':'approved'})
    ticket = request(office,'POST',official_path+'/start').json()
    replacement = request(office, 'POST', f'/projects/{pid}/files',
                          files={'file': (filename, content+b' v2', 'text/plain')}, data={'category': category}).json()
    request(office, 'POST', start_path, expected=409)
    request(office, 'POST', official_path+'/consume', expected=409, json=ticket)
    request(office, 'DELETE', f"/projects/{pid}/files/{replacement['id']}")
    request(office, 'POST', start_path, expected=409)
    expect(not request(office,'GET',f'/projects/{pid}').json()['records'], 'preview creates no official submission record')
    queue=request(admin,'GET','/admin/reviews').json()
    managed=next(x for x in queue if x['id']==pid)
    expect(managed['manual']['status']=='approved','unified manual review and resubmission')
    old=next(x for x in managed['manualHistory'] if x['status']=='returned')
    snapshot_path=f"/admin/reviews/{pid}/manual/{old['id']}"
    expect(request(admin,'GET',snapshot_path).json()[0]['body']=='实际操作说明','review history preserves original chapters')
    request(office,'GET',snapshot_path,expected=403)
    request(research,'GET','/admin/users',expected=403)
    request(office,'GET','/admin/reviews',expected=403)
    account={'username':'test_'+uuid.uuid4().hex[:12],'password':'Test-Temporary-Password!','displayName':'集成测试用户','department':'研发中心','role':'research'}
    request(admin,'POST','/admin/users',expected=400,json={**account,'department':'测试'})
    uid=request(admin,'POST','/admin/users',json=account).json()['id'];user_ids.append(uid)
    with httpx.Client(timeout=30,trust_env=False) as test_user:
        request(test_user,'POST','/auth/login',json=account)
        request(test_user,'GET','/admin/users',expected=403)
        request(admin,'PUT',f'/admin/users/{uid}',json={**account,'role':'admin'})
        request(test_user,'GET','/auth/me',expected=401)
        request(test_user,'POST','/auth/login',json=account)
        request(test_user,'GET','/admin/users')
        request(admin,'PUT',f'/admin/users/{uid}',json={**account,'role':'research'})
        request(test_user,'GET','/auth/me',expected=401)
        request(test_user,'POST','/auth/login',json=account)
        request(test_user,'GET','/admin/reviews',expected=403)
    expect(True,'account creation promotion demotion and session invalidation')
    # Exercise a real HTTP Chat Completions round trip with an isolated local test provider.
    # A dedicated test instance is mandatory; never overwrite a user's live model configuration.
    expected_config = {'base_url': 'http://127.0.0.1:1/v1', 'model': 'integration-test-isolated'}
    existing = request(admin, 'GET', '/assistant/config').json()
    assert all(existing.get(k) == v for k, v in expected_config.items()), '请将集成测试指向预先配置隔离模型的 Java/Python 实例。'
    server = ThreadingHTTPServer(("127.0.0.1", int(os.getenv('TEST_PROVIDER_PORT', '18220'))), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    cfg = {"base_url": f"http://127.0.0.1:{server.server_port}/v1", "api_key": "integration-only-secret", "model": "integration-test-model", "reasoning_effort": "high"}
    result = request(admin, "PUT", "/assistant/config", json=cfg).json()
    expect(result["api_key_set"] and "api_key" not in result, "API key is write-only")
    answer = request(research, "POST", "/assistant/chat", json={"projectId": pid, "scope": "project", "question": "源程序每页要求多少行？"}).json()
    expect(answer["mode"] == "model" and answer["sources"], "model answer carries retrieved citations")
    expect(seen[0][0] == "/v1/chat/completions" and seen[0][1]["reasoning_effort"] == "high", "provider receives Chat Completions and reasoning effort")
    expect(len(seen) == 2 and '每次只返回一个JSON对象' in seen[0][1]['messages'][0]['content']
           and '<参考资料>' in seen[1][1]['messages'][0]['content']
           and all(payload['model'] == cfg['model'] for _,payload in seen), 'configured model plans before retrieval and analysis')
    expect('PrivateEvidence' not in seen[1][1]['messages'][0]['content'], 'knowledge queries exclude project attachment text')
    msgs = request(research, "GET", "/assistant/messages", params={"projectId": pid, "scope": "project"}).json()
    expect(len(msgs) == 2 and msgs[1]["role"] == "assistant", "chat history persisted in MySQL")
    request(research, "DELETE", "/assistant/messages", params={"projectId": pid, "scope": "project"})
    expect(request(research, "GET", "/assistant/messages", params={"projectId": pid, "scope": "project"}).json() == [], "clear only current conversation")
    source = io.BytesIO()
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('index.html', FIXTURE)
    source_id = request(office, 'POST', f'/projects/{pid}/files', files={
        'file': ('前端源码.zip', source.getvalue(), 'application/zip')}, data={'category': '源程序'}).json()['id']
    jobs = f'/projects/{pid}/manual-jobs'
    job_body = {'fileId': source_id, 'url': f'http://127.0.0.1:{server.server_port}/fixture', 'browserReady': True}
    settings=jobs+'/settings'
    request(office,'POST',jobs,expected=422,json=job_body)
    request(office,'PUT',settings,expected=403,json={'url':job_body['url']})
    request(admin,'PUT',settings,expected=422,json={'url':'http://127.0.0.1:18220@example.invalid/'})
    verify_screenshot_settings_ui(admin,pid,job_body['url'])
    expect(request(office,'GET',settings).json()['url']==job_body['url'],'project screenshot entry is persisted and shared with project members')
    request(office, 'POST', jobs, expected=422, json={**job_body, 'browserReady': False})
    request(office, 'POST', jobs, expected=422, json={**job_body, 'url': 'https://example.invalid/'})
    start_index = len(seen)
    vision_start = len(seen)
    stall_review.set()
    job = start_manual_from_folder(office, pid)
    job_path = jobs + '/' + job['id']
    assert review_is_stalled.wait(timeout=20), 'the second page review did not start'
    request(research, 'GET', job_path, expected=404)
    expect(request(research, 'GET', jobs).json()['job'] is None, 'manual jobs are scoped to project and owner')
    planned = request(office, 'GET', job_path).json()
    selection = planned['result']['sourceSelection']
    expect(selection['candidates'] == 3
           and selection['groups']['frontend']['readPaths'] == ['项目样例/index.html']
           and selection['groups']['backend']['readPaths'] == ['项目样例/backend/ProjectController.java'],
           'folder paths are preserved and frontend and backend files are analyzed separately')
    request(office, 'POST', job_path + '/word', expected=404, json={'acknowledged': True})
    plan = request(office, 'GET', job_path + '/plan').json()
    expect(len(plan['shots']) == 6 and any(e['text'] == '截图计划已生成，正在打开测试站点。' for e in planned['events']),
           'the generated plan automatically starts browser capture')
    expect(plan['skipped'] == planned['result']['skippedShots']
           and plan['skipped'][0]['operationId'] == 'log-detail'
           and any(o['id'] == 'log-detail' and not o['capture'] for o in planned['result']['operations']),
           'missing data excludes an operation from screenshots without removing it from the manual')
    expect(any('后端源码分析」将改用非流式请求' in event['text'] for event in planned['events']),
           'a stream connection loss switches formats without restarting source analysis')
    request(admin,'PUT',settings,json={'url':''})
    request(office, 'POST', job_path + '/capture', expected=409)
    request(admin,'PUT',settings,json={'url':job_body['url']})
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**chrome_executable())
            try:
                page = project_page(browser, office, pid, 'source')
                with page.expect_response(lambda response: response.url.endswith(job_path + '/capture')
                                          and response.request.method == 'POST') as response:
                    page.get_by_role('button', name='重试当前步骤').click()
                assert response.value.ok, response.value.text()
                resumed = response.value.json()
                expect(resumed['status'] == 'running' and resumed['result']['captured'] == 1
                       and '保留 1 张' in resumed['events'][-1]['text'],
                       'retry cancels an active capture and preserves approved images')
            finally:
                browser.close()
    finally:
        release_review.set()
    finished = await_job(office, job_path, 'complete')
    expect(finished['result']['captured'] == 3 and {e['stage'] for e in finished['events']} == set(range(6)),
           'all six stages report progress and real browser screenshots')
    skipped = finished['result']['unreachableShots']
    expect([(s['title'], s['operationId']) for s in skipped] == [('服务异常页', None), ('异常详情', 'error-detail')]
           and '验收文字' in skipped[0]['reason'] and '所属页面无法到达' in skipped[1]['reason'],
           'an unreachable page and its dependent operation are skipped without interrupting reachable targets')
    expect([(s['operationId'], '复核仍未通过' in s['reason']) for s in finished['result']['failedShots']]
           == [('rejected-detail', True)],
           'a shot that fails every review is logged and does not block exporting the approved shots')
    expect(all(payload['model'] == cfg['model'] and payload['reasoning_effort'] == cfg['reasoning_effort']
               for _, payload in seen[start_index:]), 'manual model calls use the configured assistant model and effort')
    request(office, 'GET', job_path + '/word', expected=428)
    request(office, 'POST', job_path + '/word', expected=428, json={'acknowledged': False})
    word = request(office, 'POST', job_path + '/word', json={'acknowledged': True})
    from docx import Document
    doc = Document(io.BytesIO(word.content))
    expect(len(doc.inline_shapes) == 3 and len(doc.sections) == 2 and '版本详情' in '\n'.join(p.text for p in doc.paragraphs),
           'downloaded Word preserves template sections and embeds each real JPEG')
    captions = [p.text for p in doc.paragraphs if '待补截图' in p.text]
    expect(len(captions) == 3 and any('服务异常页' in p and '服务遇到异常' in p for p in captions)
           and any('异常详情' in p for p in captions) and any('版本详情补充视图' in p for p in captions),
           'the manual keeps sections and labels blank placeholders for missing page and operation images')
    reviews = [payload['messages'][-1]['content'] for _, payload in seen[vision_start:]
               if payload['messages'][0]['content'].startswith('操作手册任务：截图核验。')]
    requests = [json.loads(parts[0]['text']) for parts in reviews]
    expect([(item['target'], item['attempt'], item['viewport']) for item in requests] ==
           [('项目首页', 1, 'default'), ('资料管理', 1, 'default'), ('资料管理', 1, 'default'), ('查看版本详情', 1, 'default'),
            ('查看版本详情', 2, 'wide'), ('版本详情补充视图', 1, 'default'),
            ('版本详情补充视图', 2, 'wide'), ('版本详情补充视图', 3, 'focus')],
           'rejected screenshots get bounded retakes and subsequent approved screenshots are retained')
    rejected_image, approved_image = [base64.b64decode(parts[1]['image_url']['url'].split(',', 1)[1])
                                      for parts in reviews[3:5]]
    with zipfile.ZipFile(io.BytesIO(word.content)) as archive:
        media = [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
    expect(approved_image in media and rejected_image not in media and approved_image != rejected_image,
           'Word embeds the approved retake and does not embed the rejected image')
    if filename := os.getenv('TEST_MANUAL_WORD'):
        Path(filename).write_bytes(word.content)
    verify_workspace_ui(office, pid)
    request(research, 'POST', jobs + '/reset')
    expect(request(office, 'GET', jobs).json()['job']['id'] == job['id'],
           'reset only affects the current account and project')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**chrome_executable())
        try:
            page = project_page(browser, office, pid, 'source')
            toolbar = page.get_by_role('group', name='手册生成操作')
            download = toolbar.get_by_role('button', name='下载 Word 手册')
            download.wait_for()
            expect(toolbar.get_by_role('button', name='上传并送审').count() == 0,
                   'submission upload becomes available only after the reference download')
            download.click()
            declaration = page.get_by_role('dialog', name='确认手册用途')
            expect(declaration.get_by_text('我已确认，AI 生成的内容不可用于软著申请，此次生成仅用作参考内容。').is_visible(),
                   'download asks the user to acknowledge reference-only use')
            with page.expect_download() as download_event:
                declaration.get_by_role('button', name='确认下载').click()
            assert download_event.value.suggested_filename == '操作手册.docx'
            with page.expect_file_chooser() as chooser:
                toolbar.get_by_role('button', name='上传并送审').click()
            final_word = Document()
            final_word.add_paragraph('人工编辑后的最终操作手册')
            final_bytes = io.BytesIO()
            final_word.save(final_bytes)
            chooser.value.set_files({'name': '操作手册最终版.docx',
                                     'mimeType': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                                     'buffer': final_bytes.getvalue()})
            page.get_by_text('已上传 操作手册最终版.docx，待送审').wait_for()
            expect(request(office, 'GET', f'/projects/{pid}/manual').json()['status'] != 'submitted',
                   'upload alone does not submit the final file')
            with page.expect_response(lambda response: response.url.endswith('/manual/submit')
                                      and response.request.method == 'POST') as submitted:
                toolbar.get_by_role('button', name='送审', exact=True).click()
            assert submitted.value.ok, submitted.value.text()
            final_manual = submitted.value.json()
            assert final_manual['status'] == 'submitted' and final_manual['attachmentName'] == '操作手册最终版.docx'
            with page.expect_response(lambda response: response.url.endswith('/manual-jobs/reset')
                                      and response.request.method == 'POST') as response:
                page.get_by_role('button', name='重置状态').click()
            assert response.value.ok, response.value.text()
            page.get_by_text('暂无解析任务', exact=True).wait_for()
            page.reload()
            page.get_by_text('暂无解析任务', exact=True).wait_for()
            expect(page.get_by_role('button', name='下载 Word 手册').count() == 0,
                   'reset clears the manual workspace after reload')
        finally:
            browser.close()
    manual_review = next(p['manual'] for p in request(admin, 'GET', '/admin/reviews').json() if p['id'] == pid)
    manual_attachment = f"/projects/{pid}/files/{manual_review['attachmentId']}"
    expect(manual_review['status'] == 'submitted'
           and request(admin, 'GET', manual_attachment + '/download').content == final_bytes.getvalue()
           and any(n['projectId']==pid and n['kind']=='manual' for n in request(admin,'GET','/notifications').json()),
           'the administrator receives a pending review and can download the uploaded original')
    request(office, 'DELETE', manual_attachment, expected=409)
    request(admin, 'POST', f'/projects/{pid}/manual/review',
            json={'revision': manual_review['revision'], 'status': 'approved'})
    expect(request(office, 'POST', job_path + '/word', json={'acknowledged': True}).content == word.content
           and request(office, 'GET', settings).json()['url'] == job_body['url'],
           'reset preserves completed files and the saved capture entry')
    attachments = request(office, 'GET', f'/projects/{pid}').json()['files']
    archive_id = next(f['id'] for f in attachments if f['name'] == '项目样例.zip')
    active_job = request(office, 'POST', jobs + '/source', json={'fileId': archive_id}).json()
    request(office, 'POST', jobs + '/reset')
    active_path = jobs + '/' + active_job['id']
    expect(request(office, 'GET', active_path).json()['status'] == 'cancelled'
           and request(office, 'GET', jobs).json()['job'] is None,
           'reset stops an active task and does not revive older jobs')
    force_vision_rejection.set()
    try:
        blank_job = request(office, 'POST', jobs, json={**job_body, 'fileId': archive_id}).json()
        blank_path = jobs + '/' + blank_job['id']
        await_job(office, blank_path, 'complete')
    finally:
        force_vision_rejection.clear()
    blank_word = request(office, 'POST', blank_path + '/word', json={'acknowledged': True})
    blank_document = Document(io.BytesIO(blank_word.content))
    expect(len(blank_document.inline_shapes) == 0
           and sum('待补截图' in p.text for p in blank_document.paragraphs) == 6,
           'when every screenshot is missing the Word file contains all six placeholders')
    p = request(admin, "GET", f"/projects/{pid}").json()
    request(admin, "PUT", f"/projects/{pid}", json={**p, "allowedRoles": ["adminDept"]})
    request(research, "GET", f"/projects/{pid}", expected=403)
    request(research, "GET", f"/projects/{pid}/files/{one['id']}/download", expected=403)
    expect(all(x["id"] != pid for x in request(research, "GET", "/projects").json()), "project ACL enforced in list and file endpoints")
    target=request(admin,'POST','/projects',json={'name':'助手代填目标','version':'V1.0','dept':'研发中心','owner':'测试'}).json();project_ids.append(target['id'])
    new_project=request(office,'POST','/assistant/chat',json={'question':'助手代填目标的版本是什么？'}).json()
    expect(new_project['sources'][0]['project_id']==target['id'],'new project without attachments is located by name and retrieved')
    status=request(office,'POST','/assistant/chat',json={'projectId':target['id'],'scope':'project','question':'这个项目的填写和审核状态怎么样？'}).json()
    expect('待完善字段' in status['answer'] and '尚无记录' in status['answer'],'assistant reads live project status')
    request(admin,'DELETE',f'/projects/{pid}')
    archived_result=request(research,'POST','/assistant/chat',json={
        'projectId':target['id'],'question':'哪个软著的附件提到了 PrivateEvidence？'}).json()
    expect(any(c['project_id']==pid and 'PrivateEvidence' in c['excerpt'] for c in archived_result['sources']),
           'assistant finds an archived project by uploaded attachment content across project ACLs')
    expect('再次修改软件开发目的' not in seen[-1][1]['messages'][0]['content'], 'project field ACL still applies to project retrieval')
    fill={'projectId':target['id'],'page':'basic','question':'帮我从跨项目附件填写软件简称'}
    expect(not request(office,'POST','/assistant/chat',json={**fill,'hasUnsaved':True}).json().get('changed'),
           'assistant protects unsaved form input')
    with research.stream('POST', BASE+'/assistant/chat/stream',
                         json={'projectId':target['id'],'question':'源程序每页要求多少行？'}) as stream:
        stream.raise_for_status()
        events=[json.loads(line) for line in stream.iter_lines() if line]
    expect([e['type'] for e in events]==['phase','tool','ready','delta','delta','tool','done']
           and events[1]['name']=='knowledge' and events[1]['state']=='running'
           and events[-2]['state']=='finished' and events[-1]['sources']
           and ''.join(e['text'] for e in events if e['type']=='delta')==events[-1]['answer'],
           'stream forwards separate provider chunks, tool states and final citations')
    verify_assistant_fill_ui(office,target['id'],fill['question'])
    draft=request(office,'GET',f"/projects/{target['id']}").json()
    expect(draft['form']['shortName']=='来自跨项目附件的简称'
           and 'shortName' in draft['assistantReferenceFields'],'agent reads archived ZIP entry, fills draft and marks the field')
    turn = request(office,'GET','/assistant/messages',params={'projectId':target['id']}).json()[-1]
    write = next(event for event in turn['operations'] if event['action']=='fill_form')
    expect(write['projectId']==target['id'] and write['changes']==[
        {'field':'shortName','label':'软件简称','before':'','after':'来自跨项目附件的简称'}],
        'assistant persists the actual project and exact before/after values')
    expect(any(event['action']=='read_attachment' and event['sourceProject']!=write['projectName']
               for event in turn['operations']), 'the source project is separate from the write target')
    noop = request(office,'POST','/assistant/chat',json={**fill,'question':'帮我把软件简称改成来自跨项目附件的简称'}).json()
    expect(not noop['changed'] and noop['operations'][-1]['changes']==[], 'no-op fill records no field modification')
    edited=request(office,'PUT',f"/projects/{target['id']}/form",
                   json={'revision':draft['revision'],'fields':{'shortName':'人工修订简称'}}).json()
    expect('shortName' not in edited['assistantReferenceFields'],'manual edit clears the reference marker')
    recall = {'projectId':target['id'],'page':'basic','question':'刚才具体修改了什么？'}
    memory = request(office,'POST','/assistant/chat',json=recall).json()
    expect('来自跨项目附件的简称' in memory['answer'], 'follow-up remembers the saved value after a later manual edit')
    expect('没有已保存的修改' in request(admin,'POST','/assistant/chat',json=recall).json()['answer'],
           'assistant memory is isolated by account')
    expect('没有已保存的修改' in request(office,'POST','/assistant/chat',json={**recall,'scope':'project'}).json()['answer'],
           'assistant memory is isolated by conversation scope')
    request(office,'POST','/assistant/chat',json={**recall,'question':'哪个软著的附件提到了 PrivateEvidence？'})
    follow = request(office,'POST','/assistant/chat',json={**recall,'question':'刚才那个项目的版本呢？'}).json()
    expect(follow['operations'][-1]['projectId']==pid, 'project follow-up uses the previously located target')
    blocked = request(office,'POST','/assistant/chat',json={**recall,'question':'帮我把刚才查的项目的软件简称改成测试'}).json()
    expect('请切换' in blocked['answer'] and not blocked.get('changed'),
           'a remembered project cannot redirect a write to a different current page')
    request(office,'DELETE','/assistant/messages',params={'projectId':target['id']})
    expect('没有已保存的修改' in request(office,'POST','/assistant/chat',json=recall).json()['answer'],
           'cleared turns are excluded from subsequent memory')
    request(research,'POST','/assistant/chat',expected=403,json={
        'projectId':target['id'],'page':'basic','question':'帮我填写著作权人'})
    request(office,'POST',f"/projects/{target['id']}/files",
            files={'file':('操作手册联调.txt',('使用说明\n\n'+'无关段落内容。'*4000+'\n\n软件简称：手册示例').encode(),
                           'text/plain')},data={'category':'技术文档'})
    with office.stream('POST',BASE+'/assistant/chat/stream',
                       json={'projectId':target['id'],'page':'basic','question':'根据我刚上传的操作手册填写基础信息'}) as stream:
        stream.raise_for_status()
        events=[json.loads(line) for line in stream.iter_lines() if line]
    expect([(e['name'],e['state']) for e in events if e['type']=='tool']==[
        ('read_attachment','running'),('read_attachment','finished'),('fill_form','running'),('fill_form','finished')]
        and events[-1]['changed'] and '仍需补充：著作权人' in events[-1]['answer']
        and events[-1]['project']['form']['shortName']=='手册示例',
        'assistant chooses the recent project attachment and fills evidenced fields beyond the first page')
    request(office, "POST", "/assistant/knowledge", expected=403, json={"title": "x", "content": "y"})
    print(f"验证通过：{checks}组关键断言及全部HTTP状态检查；使用真实Java、Python和本机MySQL。")
finally:
    if server:
        try:
            clients["admin"].put(BASE + "/assistant/config", json={**expected_config, 'clear_api_key': True, 'reasoning_effort': 'default'})
        except Exception:
            pass
        server.shutdown()
        server.server_close()
    for client in clients.values():
        try:
            client.post(BASE + "/auth/logout")
        finally:
            client.close()
    if project_ids:
        # IDs are generated by this test. No existing project or user is deleted.
        quoted = ",".join("'" + x.replace("'", "''") + "'" for x in project_ids)
        # Remove only disk files created for test projects.
        lookup=f"SELECT storage_path FROM attachments WHERE project_id IN ({quoted}) AND storage_path IS NOT NULL;"
        paths=subprocess.run(['mysql','-h',env.get('DB_HOST','127.0.0.1'),'-P',env.get('DB_PORT','3306'),'-u',env['DB_USERNAME'],'-N',env.get('DB_NAME','copyright_workspace'),'-e',lookup],env={**os.environ,'MYSQL_PWD':env['DB_PASSWORD']},capture_output=True,text=True,check=True)
        attachment_dir=Path(env.get('ATTACHMENT_DIR',ROOT/'data/attachments')).resolve()
        for name in paths.stdout.splitlines():
            path=Path(name)
            if path.parent.resolve()==attachment_dir:path.unlink(missing_ok=True)
        user_cleanup=''
        for uid in user_ids:
            user_cleanup+=f"DELETE FROM user_sessions WHERE user_id='{uid}';DELETE FROM users WHERE id='{uid}';"
        sql = "START TRANSACTION;" + "".join(f"DELETE FROM {table} WHERE project_id IN ({quoted});" for table in ["manual_reviews", "project_manuals", "chat_messages", "application_records", "field_reviews", "project_fields", "activity_logs", "attachments"]) + f"DELETE FROM projects WHERE id IN ({quoted});"+user_cleanup+"COMMIT;"
        subprocess.run(["mysql", "--host=" + env.get("DB_HOST", "127.0.0.1"), "--port=" + env.get("DB_PORT", "3306"), "--user=" + env["DB_USERNAME"], env.get("DB_NAME", "copyright_workspace")], input=sql.encode(), env={**os.environ, "MYSQL_PWD": env["DB_PASSWORD"]}, check=True)
