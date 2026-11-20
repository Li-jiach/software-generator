"""End-to-end checks against running Java/Python/MySQL, with disposable records only."""
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
            data = json.loads(payload['messages'][-1]['content'])
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
                    plan={'action':'fill_form','args':{'fields':{'shortName':short_name}}}
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
                    plan={'action':'fill_form','args':{'fields':{'shortName':'手册示例'},'missing':'著作权人'}}
                content=json.dumps(plan,ensure_ascii=False)
            elif question=='帮我填写著作权人':
                content=json.dumps({'action':'fill_form','args':{'fields':{'copyrightOwner':'越权修改'}}})
            elif question=='这个项目的填写和审核状态怎么样？':
                content=json.dumps({'action':'status'})
            else:
                content=json.dumps({'action':'knowledge','args':{'query':'源程序每页行数'}})
        if payload.get('stream'):
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            for part in (content[:8],content[8:]):
                event=json.dumps({'choices':[{'delta':{'content':part},'finish_reason':None}]},ensure_ascii=False)
                self.wfile.write(('data: '+event+'\n\n').encode())
                self.wfile.flush()
                time.sleep(.15)
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
        {'id': 'list', 'moduleId': 'files', 'title': '资料管理', 'description': '查看资料和版本。',
         'source': '项目样例/index.html', 'steps': [navigate], 'visibleText': '资料管理'},
    ]
    match task:
        case '目录文件筛选':
            assert set(data['directory']) == {'项目样例/index.html','项目样例/backend/ProjectController.java','项目样例/tools/demo.py'}
            return {'paths': ['项目样例/index.html','项目样例/backend/ProjectController.java']}
        case '源码分批盘点':
            assert any('版本详情' in entry['text'] for entry in data)
            assert any('ProjectController' in entry['text'] for entry in data)
            assert all('UNSELECTED_SCRIPT' not in entry['text'] for entry in data)
            return {'facts': 'index.html 含项目首页、资料管理和版本详情对话框。'}
        case '功能目录':
            return {'overview': '用于查阅测试项目的资料与版本。', 'modules': [
                {'id': 'workspace', 'parentId': None, 'title': '项目工作区'},
                {'id': 'files', 'parentId': 'workspace', 'title': '资料管理'},
            ]}
        case '页面与点击路径':
            return {'pages': pages}
        case '主要功能操作':
            return {'operations': [{'id': 'detail', 'pageId': 'list', 'title': '查看版本详情',
                                    'description': '弹窗显示版本信息。', 'instructions': ['点击查看详情。', '读取版本记录。'], 'capture': True}]}
        case '截图脚本计划':
            return {'targets': [{'operationId': 'detail', 'steps': [detail], 'visibleText': '版本详情'}]}
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
        browser = playwright.chromium.launch(executable_path=env.get('MANUAL_CHROMIUM_PATH') or None)
        try:
            page = project_page(browser, client, project_id, 'source')
            page.get_by_label('选择项目文件夹').set_input_files(folder)
            page.get_by_text('已在默认浏览器打开测试站点', exact=False).click()
            with page.expect_response(lambda response: response.url.endswith('/manual-jobs')
                                      and response.request.method == 'POST') as response:
                page.get_by_role('button', name='开始分析').click()
            result = response.value
            assert result.ok, result.text()
            return result.json()
        finally:
            browser.close()


def verify_screenshot_settings_ui(client, project_id, url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=env.get('MANUAL_CHROMIUM_PATH') or None)
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
        browser = playwright.chromium.launch(executable_path=env.get('MANUAL_CHROMIUM_PATH') or None)
        try:
            page = project_page(browser, client, project_id, 'basic')
            page.get_by_role('button', name='软著助手', exact=True).click()
            page.get_by_role('textbox', name='向软著助手提问').fill(question)
            page.get_by_role('button', name='发送问题').click()
            page.get_by_text('AI 仅供参考', exact=True).wait_for()
            expect(page.get_by_label('软件简称').input_value() == '来自跨项目附件的简称',
                   'the assistant updates and marks the visible form input')
        finally:
            browser.close()


def verify_workspace_ui(client, project_id):
    from playwright.sync_api import sync_playwright
    origin = BASE.removesuffix('/api')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=env.get('MANUAL_CHROMIUM_PATH') or None)
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
            page.get_by_role('link', name='下载 Word 手册').wait_for()
            page.set_viewport_size({'width': 390, 'height': 844})
            expect(page.get_by_role('heading', name='解析进程').is_visible() and page.get_by_label('当前项目').is_visible()
                   and page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'manual generation and selector fit a mobile viewport')
        finally:
            browser.close()


def verify_application_ui(client, admin, project_id):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=env.get('MANUAL_CHROMIUM_PATH') or None)
        try:
            page = project_page(browser, client, project_id, 'rpa')
            page.get_by_role('heading', name='申报流程与执行记录').wait_for()
            expect(page.locator('.sidebar .brand').inner_text().strip() == '', 'sidebar brand title is removed')
            page.get_by_role('button', name='启动申报预览').click()
            spinner = page.locator('.step-spinner')
            spinner.wait_for()
            expect(spinner.evaluate('el => getComputedStyle(el).animationName') == 'application-spin',
                   'current application step displays an animated spinner')
            page.get_by_text('填写及上传流程预览完成，等待接入官网', exact=False).wait_for()
            expect(page.locator('.timeline-point.good').count() == 2, 'completed preview steps display check marks')
            page.set_viewport_size({'width': 390, 'height': 844})
            expect(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'application preview fits a mobile viewport')
            expect(page.get_by_role('heading', name='申报页面', exact=True).count() == 0
                   and page.get_by_role('heading', name='人工合规核验', exact=True).count() == 0,
                   'obsolete application panels are removed')
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
    values = {}
    for f in fields:
        values[f["id"]] = f["opts"][0] if f.get("type") == "select" else "2026-01-01" if f.get("type") == "date" else "1" if f.get("type") == "number" else "验证环境与功能说明"
    values.update(fullName="联调验证项目（临时）", version="V1.0", mainFunction="本系统提供项目登记、分工填报、材料管理、审核核验、进度查询以及知识检索功能，面向研发人员和知识产权管理人员，支持数据记录、附件留存、业务查询、资料归档与工作协同。" * 10)
    p = request(admin, "PUT", f"/projects/{pid}/form", json={"revision": p["revision"], "fields": values}).json()
    expect(not p["validation"], "server-side field validation")
    request(office, "POST", f"/projects/{pid}/form/submit", expected=409, json={"revision": invalid["revision"]})
    p = request(office, "POST", f"/projects/{pid}/form/submit", json={"revision": p["revision"]}).json()
    expect(p["formStatus"] == "submitted", "submit for review")
    request(research, "POST", f"/projects/{pid}/form/review", expected=403, json={"field": "all", "status": "approved"})
    request(admin, "POST", f"/projects/{pid}/form/review", expected=400, json={"field": "purpose", "status": "returned", "comment": ""})
    p = request(admin, "POST", f"/projects/{pid}/form/review", json={"field": "purpose", "status": "returned", "comment": "请补充实际开发目的"}).json()
    expect(p["formStatus"] == "returned", "review rejection")
    p = request(research, "PUT", f"/projects/{pid}/form", json={"revision": p["revision"], "fields": {"purpose": "提升科研机构的软件资料管理效率"}}).json()
    request(office, "POST", f"/projects/{pid}/form/submit")
    p = request(admin, "POST", f"/projects/{pid}/form/review", json={"field": "all", "status": "approved"}).json()
    expect(p["formStatus"] == "approved", "bulk approval")
    p = request(research, "PUT", f"/projects/{pid}/form", json={"revision": p["revision"], "fields": {"purpose": "再次修改开发目的"}}).json()
    expect(p["formStatus"] == "draft" and "purpose" not in p["formReviews"], "changing reviewed value invalidates approval")
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
    manual=request(admin,'POST',f'/projects/{pid}/manual/review',json={'revision':manual['revision'],'status':'returned','comment':'补充操作结果'}).json()
    expect(any(n['projectId']==pid and n['kind']=='manual' and n['status']=='returned' for n in request(office,'GET','/notifications').json()),'returned manual is assigned to project contributors')
    manual=request(office,'PUT',f'/projects/{pid}/manual',json={'revision':manual['revision'],'chapters':[{'id':'ch1','title':'测试章节','body':'实际操作说明与结果','verified':True}]}).json()
    manual=request(office,'POST',f'/projects/{pid}/manual/submit',json={'revision':manual['revision']}).json()
    request(admin,'POST',f'/projects/{pid}/manual/review',json={'revision':manual['revision'],'status':'approved'})
    material_path = f'/projects/{pid}/application-materials'
    precheck_path = f'/projects/{pid}/application-precheck'
    start_path = f'/projects/{pid}/application-preview/start'
    request(office, 'POST', start_path, expected=409)
    request(research, 'POST', start_path, expected=403, headers={'X-Role': 'admin'})
    request(research, 'POST', material_path+'/source/submit', expected=422, json={'attachmentId': zipped['id']})
    for kind, category, filename in [('source', '源程序鉴别材料', '源程序鉴别材料.txt'), ('ownership', '权属材料', '权属证明.txt')]:
        artifact = request(research, 'POST', f'/projects/{pid}/files',
                           files={'file': (filename, content, 'text/plain')}, data={'category': category}).json()
        review_path = material_path + f'/{kind}/review'
        submit_path = material_path + f'/{kind}/submit'
        submission = request(research, 'POST', submit_path, json={'attachmentId': artifact['id']}).json()
        expect(any(n['projectId']==pid and n['kind']==kind for n in request(admin,'GET','/notifications').json()),
               'material submission sends an administrator notification')
        body = {'reviewId': submission['reviewId'], 'status': 'approved'}
        request(research, 'POST', review_path, expected=403, json=body)
        request(admin, 'POST', review_path, json={**body,'status':'returned','comment':'请重新核对'})
        expect(any(n['projectId']==pid and n['kind']==kind and n['status']=='returned'
                   for n in request(research,'GET','/notifications').json()), 'returned material notifies project contributors')
        retry = request(research, 'POST', submit_path, json={'attachmentId': artifact['id']}).json()
        request(admin, 'POST', review_path, expected=409, json=body)
        request(admin, 'POST', review_path, json={**body,'reviewId':retry['reviewId']})
    request(office, 'POST', start_path, expected=409)
    request(office, 'POST', f'/projects/{pid}/form/submit')
    request(admin, 'POST', f'/projects/{pid}/form/review', json={'field':'all','status':'approved'})
    expect(all(check['status']=='approved' for check in request(office,'GET',precheck_path).json()['checks']),
           'the live precheck verifies all four approvals')
    expect(request(office,'POST',start_path).json()=={'mode':'preview'}, 'approved materials start the preview')
    verify_application_ui(office, admin, pid)
    replacement = request(office, 'POST', f'/projects/{pid}/files',
                          files={'file': (filename, content+b' v2', 'text/plain')}, data={'category': category}).json()
    request(office, 'POST', start_path, expected=409)
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
    job = start_manual_from_folder(office, pid)
    job_path = jobs + '/' + job['id']
    request(research, 'GET', job_path, expected=404)
    expect(request(research, 'GET', jobs).json()['job'] is None, 'manual jobs are scoped to project and owner')
    planned = await_job(office, job_path, 'review')
    expect(planned['result']['sourceSelection'] == {'candidates': 3, 'paths': [
        '项目样例/index.html','项目样例/backend/ProjectController.java']},
        'folder paths are preserved and only selected frontend and backend files are read')
    request(office, 'GET', job_path + '/word', expected=404)
    plan = request(office, 'GET', job_path + '/plan').json()
    expect(len(plan['shots']) == 3 and 'captured' not in planned['result'], 'plan covers pages and modal without capturing before confirmation')
    request(admin,'PUT',settings,json={'url':''})
    request(office, 'POST', job_path + '/capture', expected=409)
    request(admin,'PUT',settings,json={'url':job_body['url']})
    request(office, 'POST', job_path + '/capture')
    finished = await_job(office, job_path, 'complete')
    expect(finished['result']['captured'] == 3 and {e['stage'] for e in finished['events']} == set(range(6)),
           'all six stages report progress and real browser screenshots')
    expect(all(payload['model'] == cfg['model'] and payload['reasoning_effort'] == cfg['reasoning_effort']
               for _, payload in seen[start_index:]), 'manual model calls use the configured assistant model and effort')
    word = request(office, 'GET', job_path + '/word')
    from docx import Document
    doc = Document(io.BytesIO(word.content))
    expect(len(doc.inline_shapes) == 3 and len(doc.sections) == 2 and '版本详情' in '\n'.join(p.text for p in doc.paragraphs),
           'downloaded Word preserves template sections and embeds each real JPEG')
    if filename := os.getenv('TEST_MANUAL_WORD'):
        Path(filename).write_bytes(word.content)
    verify_workspace_ui(office, pid)
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
    expect('再次修改开发目的' not in seen[-1][1]['messages'][0]['content'], 'project field ACL still applies to project retrieval')
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
    edited=request(office,'PUT',f"/projects/{target['id']}/form",
                   json={'revision':draft['revision'],'fields':{'shortName':'人工修订简称'}}).json()
    expect('shortName' not in edited['assistantReferenceFields'],'manual edit clears the reference marker')
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
