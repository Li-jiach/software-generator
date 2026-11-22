"""Replay the reviewed, declarative screenshot plan in an isolated browser."""

import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


RepairMode = Literal['focus', 'wide', 'tall']
REPAIR_MODES = ('focus', 'wide', 'tall')
VIEWPORTS = {'default': (1366, 900), 'focus': (1366, 900), 'wide': (1600, 1050), 'tall': (1366, 1200)}
MAX_CAPTURE_ATTEMPTS = 3


class ManualError(Exception):
    pass


class ShotFailure(ManualError):
    pass


class UnreachableShot(ShotFailure):
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
    from playwright.async_api import Error

    browser_path = os.getenv('MANUAL_CHROMIUM_PATH', '')
    executable = {'executable_path': browser_path} if browser_path else {'channel': 'chrome'}
    try:
        browser = await playwright.chromium.launch(
            **executable, headless=True, timeout=12000,
            chromium_sandbox=True, args=['--no-proxy-server'],
        )
    except Exception:
        raise ManualError('无法启动 Google Chrome。请安装 Chrome，或将 MANUAL_CHROMIUM_PATH 指向 Chrome 可执行文件。') from None
    is_chrome = False
    try:
        page = await browser.new_page()
        try:
            await page.goto('chrome://version/', timeout=5000)
            is_chrome = await page.evaluate(
                "navigator.userAgentData?.brands.some(item => item.brand === 'Google Chrome')"
            )
        finally:
            await page.close()
    except Error:
        is_chrome = False
    finally:
        if not is_chrome:
            await browser.close()
    if not is_chrome:
        raise ManualError('截图必须使用 Google Chrome，请检查 MANUAL_CHROMIUM_PATH。')
    return browser


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
        raise ManualError('未能验证 Google Chrome 的开发者工具连接。') from None


async def capture(url: str, shots: list[Shot], folder: Path, images, report, review, skip):
    from playwright.async_api import Error, TimeoutError

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

    async def take_image(browser, shot, mode):
        width, height = VIEWPORTS[mode]
        context = await browser.new_context(viewport={'width': width, 'height': height},
                                            accept_downloads=False, service_workers='block')
        try:
            await context.route('**/*', restrict)
            await context.route_web_socket('**/*', block_socket)
            page = await context.new_page()
            page.set_default_timeout(4500)
            try:
                response = await page.goto(url, wait_until='domcontentloaded', timeout=16000)
            except Error:
                if not browser.is_connected():
                    raise
                raise UnreachableShot('无法打开测试站点入口。') from None
            if not response or not response.ok:
                raise UnreachableShot('测试站点没有返回可用页面。')
            for click in shot.steps:
                locator = page.get_by_role(click.role, name=click.label, exact=True)
                try:
                    await locator.click(timeout=4500)
                except TimeoutError:
                    raise UnreachableShot(f'无法点击「{click.label}」。') from None
                except Error:
                    if await locator.count() > 1:
                        raise UnreachableShot(f'「{click.label}」匹配到多个控件。') from None
                    raise
            checkpoints = [text.strip() for text in re.split(r'[；;\n]+', shot.visibleText) if text.strip()]
            if not checkpoints or len(checkpoints) > 6:
                raise ShotFailure('截图验收文字不合法。')
            targets = [page.get_by_text(text, exact=True).filter(visible=True).first for text in checkpoints]
            for checkpoint, target in zip(checkpoints, targets):
                try:
                    await target.wait_for(state='visible')
                except TimeoutError:
                    raise UnreachableShot(f'页面未显示验收文字「{checkpoint}」。') from None
            try:
                if mode == 'focus':
                    await targets[0].evaluate("(element) => element.scrollIntoView({block: 'center', inline: 'nearest'})")
                else:
                    await targets[0].scroll_into_view_if_needed()
                return await page.screenshot(type='jpeg', quality=82, animations='disabled', timeout=6000)
            except TimeoutError:
                raise ShotFailure('浏览器未在规定时间内完成取景和截图。') from None
            except Error:
                if not browser.is_connected():
                    raise
                raise ShotFailure('浏览器无法为当前页面生成截图。') from None
        finally:
            await context.close()

    async def verified_image(browser, shot):
        mode = 'default'
        used_modes = set()
        for attempt in range(1, MAX_CAPTURE_ATTEMPTS + 1):
            used_modes.add(mode)
            try:
                image = await take_image(browser, shot, mode)
            except UnreachableShot as exc:
                if attempt == 1:
                    raise
                raise ShotFailure(f'重拍时无法恢复待核验画面。{exc}') from None
            approved, reason, repair = await review(shot, image, attempt, mode)
            if approved:
                return image
            if attempt == MAX_CAPTURE_ATTEMPTS:
                raise ShotFailure(f'重拍后截图复核仍未通过。{reason}')
            mode = repair if repair not in used_modes else next(option for option in REPAIR_MODES if option not in used_modes)

    unreachable_pages = set()
    total = sum(path.stat().st_size for path in images.values())
    async with browser_session() as playwright:
        browser = await launch(playwright)
        try:
            for shot in shots:
                if shot.id in images:
                    continue
                if shot.pageId in unreachable_pages:
                    await skip(shot, UnreachableShot('所属页面无法到达。'))
                    continue
                try:
                    image = await verified_image(browser, shot)
                except ShotFailure as exc:
                    if isinstance(exc, UnreachableShot) and shot.operationId is None:
                        unreachable_pages.add(shot.pageId)
                    await skip(shot, exc)
                    continue
                total += len(image)
                if total > 38_000_000:
                    raise ManualError('截图总体积过大，请拆分项目范围后重试。')
                path = folder / f'{shot.id}.jpg'
                path.write_bytes(image)
                images[shot.id] = path
                await report(shot.title, len(images), len(shots))
        finally:
            await browser.close()
