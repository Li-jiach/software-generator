"""Replay the reviewed, declarative screenshot plan in an isolated browser."""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ManualError(Exception):
    pass


class Click(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str = Field(min_length=1, max_length=120)
    role: str = Field(pattern=r'^(button|link|tab|menuitem|treeitem)$')

    @field_validator('label')
    @classmethod
    def read_only_label(cls, label):
        label = label.strip()
        if not label or re.search(r'删除|移除|提交|保存|注销|退出|导入|上传|发送|支付|确认|登录|授权|通过|退回|发布|delete|remove|submit|save|sign.?in|log.?in|sign.?out|upload|approve|purchase|confirm', label, re.I):
            raise ValueError('only navigation and read-only UI actions are permitted')
        return label


class Shot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,47}$')
    pageId: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,47}$')
    operationId: str | None = Field(default=None, pattern=r'^[a-z0-9][a-z0-9_-]{0,47}$')
    title: str = Field(min_length=1, max_length=120)
    steps: list[Click] = Field(max_length=16)
    visibleText: str = Field(min_length=1, max_length=160)


def capture_origin(value):
    try:
        url = urlsplit(value)
        if (url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port
                or url.netloc != f'127.0.0.1:{url.port}' or url.username or url.password
                or '\\' in value or any(c.isspace() for c in value)):
            raise ValueError()
        return f'http://127.0.0.1:{url.port}'
    except ValueError:
        raise ManualError('截图入口须使用 http://127.0.0.1:端口 的本机测试地址。') from None


def browser_session():
    from playwright.async_api import async_playwright
    return async_playwright()


async def launch(playwright):
    browser_path = os.getenv('MANUAL_CHROMIUM_PATH', '')
    try:
        return await playwright.chromium.launch(
            executable_path=browser_path or None, headless=True, timeout=12000,
            chromium_sandbox=True, args=['--no-proxy-server'],
        )
    except Exception:
        raise ManualError('无法启动独立 Chromium。请安装 Playwright Chromium，或配置 MANUAL_CHROMIUM_PATH。') from None


async def preflight(url: str):
    capture_origin(url)
    try:
        async with browser_session() as playwright:
            browser = await launch(playwright)
            try:
                cdp = await browser.new_browser_cdp_session()
                version = await cdp.send('Browser.getVersion')
                return str(version['product'])
            finally:
                await browser.close()
    except ManualError:
        raise
    except Exception:
        raise ManualError('未能验证独立 Chromium 的开发者连接；没有修改默认浏览器的设置。') from None


async def capture(url: str, shots: list[Shot], folder: Path, report):
    origin = capture_origin(url)

    async def restrict(route):
        req = route.request
        try:
            allowed = capture_origin(req.url) == origin and req.method in {'GET', 'HEAD'}
        except ManualError:
            allowed = False
        if not allowed or req.resource_type in {'websocket', 'eventsource'}:
            await route.abort()
            return
        try:
            # Do not follow redirects in the proxy; every redirect must pass the same route check.
            response = await route.fetch(max_redirects=0, timeout=12000)
            await route.fulfill(response=response)
            await response.dispose()
        except Exception:
            await route.abort()

    async def block_socket(socket):
        await socket.close()

    results = {}
    total = 0
    async with browser_session() as playwright:
        browser = await launch(playwright)
        try:
            for shot in shots:
                context = await browser.new_context(viewport={'width': 1366, 'height': 900},
                                                    accept_downloads=False, service_workers='block')
                await context.route('**/*', restrict)
                await context.route_web_socket('**/*', block_socket)
                try:
                    page = await context.new_page()
                    page.set_default_timeout(4500)
                    response = await page.goto(url, wait_until='domcontentloaded', timeout=16000)
                    if not response or not response.ok:
                        raise ManualError('测试站点没有返回可用页面。')
                    for click in shot.steps:
                        locator = page.get_by_role(click.role, name=click.label, exact=True)
                        await locator.click(timeout=4500)
                    checkpoints = [text.strip() for text in re.split(r'[；;\n]+', shot.visibleText) if text.strip()]
                    if not checkpoints or len(checkpoints) > 6:
                        raise ManualError('截图验收文字不合法。')
                    for text in checkpoints:
                        await page.get_by_text(text, exact=True).filter(visible=True).first.wait_for(state='visible')
                    image = await page.screenshot(type='jpeg', quality=82, animations='disabled', timeout=6000)
                except Exception:
                    raise ManualError(f'无法确认截图「{shot.title}」的页面或控件。请检查站点、角色和点击路径后重试。') from None
                finally:
                    await context.close()
                total += len(image)
                if total > 38_000_000:
                    raise ManualError('截图总体积过大，请拆分项目范围后重试。')
                path = folder / f'{shot.id}.jpg'
                path.write_bytes(image)
                results[shot.id] = path
                await report(shot.title, len(results), len(shots))
        finally:
            await browser.close()
    return results
