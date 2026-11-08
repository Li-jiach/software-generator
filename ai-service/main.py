import json
import os
import re
from typing import Any, Dict, List
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Material Studio AI Service")

COMPONENT_INTRO_RULE = (
    "系统、模块、页面组件只需要组件介绍，写入 contentSummary，不生成 operation 或操作介绍。"
    "介绍应详细说明组件的用途、功能范围、业务作用和下属功能的组织关系，"
    "按层级各有侧重，不重复子组件的详细说明，不写点击步骤，只依据输入事实。"
)

SCREENSHOT_OPERATION_RULE = (
    "截图的 contentSummary 只概括界面用途；operation 必须详细表述该截图中展示的功能。"
    "按界面的业务区域组织说明，涵盖可辨认的信息展示区、统计指标、图表、列表及其列、表单字段，"
    "说明各区域的用途、展示的数据含义，以及用户可以在该界面完成的业务操作。"
    "同时逐项说明所有可辨认的按钮，包括工具栏按钮、列表每行的操作按钮、弹窗的确认与取消按钮，"
    "以及可见的菜单、筛选和分页控件。使用界面上的实际名称，说明功能、必要的输入或选择、"
    "操作步骤及有依据的结果；只读界面应详细说明信息查看和各区域的作用。"
    "写成连贯、正式的软件操作手册正文，可用多段或编号步骤组织内容，"
    "不得仅罗列控件名称或用一句界面概述替代功能说明，也不得在重构时删减功能说明。"
    "operation 直接输出操作说明正文，不加‘截图内容：’等前缀，不用【】包裹。"
    "只描述图片和已提供素材能证实的内容，不编造隐藏菜单、按钮、字段、结果或行为；"
    "无法辨认的控件或无法确认的行为须明确说明，不能猜测。"
)


def screenshot_operation(value: Any) -> str:
    result = str(value or "").strip()
    result = re.sub(r"^截图内容\s*[:：]\s*", "", result).strip()
    if result.startswith("【") and result.endswith("】"):
        result = result[1:-1].strip()
    return result


def normalize_text(value: Any) -> str:
    """Normalize text only for duplicate detection; preserve the original output."""
    return re.sub(r"[\s，,。；;：:、（）()【】'\"“”‘’]", "", str(value or "")).lower()


def unique_sentences(value: Any, previous: List[str]) -> str:
    """Remove sentences already emitted by an ancestor or an earlier sibling."""
    sentences = re.split(r"(?<=[。！？!?；;])\s*|\n+", str(value or "").strip())
    kept: List[str] = []
    known = [normalize_text(item) for item in previous if normalize_text(item)]
    for sentence in sentences:
        cleaned = sentence.strip()
        key = normalize_text(cleaned)
        if not key:
            continue
        if any(key == item or (key in item or item in key) for item in known if key == item or (len(item) >= 8 and len(key) >= 8)):
            continue
        kept.append(cleaned)
        known.append(key)
    return "\n".join(kept).strip()


def restructure_node_order(nodes: List[Dict[str, Any]], tree: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the manual's parent-first canvas order, then preserve unlinked nodes."""
    by_id = {str(node.get("id")): node for node in nodes}
    ordered: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def visit(item: Any) -> None:
        if not isinstance(item, dict):
            return
        node_id = str(item.get("id"))
        node = by_id.get(node_id)
        if node and node_id not in seen:
            seen.add(node_id)
            ordered.append(node)
        for child in item.get("children") or []:
            visit(child)

    for root in tree:
        visit(root)
    ordered.extend(node for node in sorted(nodes, key=lambda value: (float(value.get("y") or 0), float(value.get("x") or 0))) if str(node.get("id")) not in seen)
    return ordered


class AiSettings(BaseModel):
    endpoint: str = ""
    api_key: str = ""
    model: str = ""
    mode: str = "chat"


def settings(payload: Dict[str, Any]) -> AiSettings:
    value = payload.get("settings") or {}
    config = AiSettings(**value)
    if not config.endpoint.strip() or not config.model.strip():
        raise HTTPException(status_code=400, detail="未配置 AI 地址或模型名称")
    return config


@app.post("/optimize")
async def optimize(payload: Dict[str, Any]):
    config = settings(payload)
    field = payload.get("field", "")
    limits = {"purpose": 50, "industry": 50, "function": 200, "feature": 100}
    limit = limits.get(field)
    prompt = (
        "你是软著申请表编辑。只优化以下字段的表达，保留原有事实，不新增功能或信息。"
        f"输出不超过{limit or 200}个汉字。必须只返回一个合法 JSON 对象，"
        '格式为 {"optimized_text":"优化后的正文"}。'
        "不要输出说明、理由、标题、Markdown 或其他字段。"
        f"\n字段：{field}\n原文：{payload.get('text', '')}"
    )
    result = await call_model(prompt, config)
    optimized = parse_optimized_text(result)
    if not optimized:
        raise HTTPException(status_code=502, detail="AI 未按要求返回优化正文，原文未被修改")
    return {"text": optimized, "source": "model"}


@app.post("/test-connection")
async def test_connection(payload: Dict[str, Any]):
    config = settings(payload)
    await call_model("请只回复：连接成功", config)
    return {"ok": True}


@app.post("/generate-component")
async def generate_component(payload: Dict[str, Any]):
    config = settings(payload)
    node = payload.get("node") or {}
    node_type = node.get("type", "component")
    is_screenshot = node_type in ("screenshot", "screenshot-group")
    subject_rule = (
        "输入图片按操作顺序排列，请综合全部图片生成一份内容简介和操作介绍。后续图片是同一操作过程的上下文，不逐图输出文本，不使用截图编号、文件名或截图节点名称作为标题或主语。"
        if is_screenshot else f"直接使用组件名称“{node.get('name', '未命名组件')}”作为句子主语。"
    )
    component_name = "" if is_screenshot else f"组件名称：{node.get('name', '未命名组件')}"
    children = payload.get("children") or []
    direction = (payload.get("direction") or "").strip()
    child_text = "\n".join(f"- {item.get('name', '子功能')}：{(item.get('generated') or {}).get('contentSummary', '')}" for item in children)
    output_format = "标题：...\n内容简介：...\n操作介绍：..." if is_screenshot else "标题：...\n内容简介：..."
    supplied_title = str(node.get("title") or node.get("name") or "").strip()
    if is_screenshot and re.fullmatch(r"截图\s*\d+", supplied_title):
        supplied_title = ""
    prompt = f"""你是软件操作手册编辑。请根据软著基础信息、组件类型、组件名称和下属组件素材，生成正式的中文手册正文。
输出格式必须严格为：
{output_format}
正文不要使用“该组件”“此组件”“该页面”等泛化前缀。{subject_rule}只使用提供的事实，不要虚构按钮、字段、菜单或结果。组件类型：{node_type}
{SCREENSHOT_OPERATION_RULE if is_screenshot else COMPONENT_INTRO_RULE}
标题要求：{f'使用用户指定标题“{supplied_title}”。' if supplied_title else '根据截图可见的主体和功能生成简洁准确的标题，不使用截图编号或文件名。'}
{component_name}
软著基础信息：{payload.get('profile') or {}}
下属组件素材：
{child_text or '无'}
本次修改方向：{direction or '无'}"""
    images = node.get("images") or ([node.get("image")] if node.get("image") else [])
    result = await call_model(prompt, config, images)
    pair = parse_pair(result)
    if is_screenshot:
        pair["operation"] = screenshot_operation(pair.get("operation"))
    else:
        pair.pop("operation", None)
    if not pair.get("contentSummary") or (is_screenshot and not pair.get("operation")):
        raise HTTPException(status_code=502, detail="AI 返回内容不完整")
    pair["title"] = supplied_title or pair.get("title") or ("功能操作界面" if is_screenshot else "未命名组件")
    return {"id": node.get("id"), **pair}


@app.post("/generate-full")
async def generate_full(payload: Dict[str, Any]):
    config = settings(payload)
    tree = payload.get("tree") or []
    prompt = f'''你是软件著作权操作手册主编。请参考软件操作手册的章节结构，将给定软著基础信息和画布组件树整理成一份完整、连贯、正式的中文操作手册。
完整保留所有组件、父子层级及画布从上到下的顺序。每个父组件先写组件介绍，然后紧接其子组件；描述各司其职，合并重复介绍，不重复父组件已覆盖的内容。只使用提供的事实，不得编造按钮、字段、流程、结果或业务能力。每个组件都必须有简洁准确的 title；如果组件名称是“截图 N”这类默认名称，必须根据截图可见内容生成标题。
{COMPONENT_INTRO_RULE}
{SCREENSHOT_OPERATION_RULE}
只返回合法 JSON，格式为 {{"nodes":{{"组件ID":{{"title":"...","contentSummary":"详细的组件介绍"}}}},"screenshots":{{"截图ID":{{"title":"...","contentSummary":"...","operation":"详细的界面功能和操作说明正文"}}}}}}。所有组件 ID 都必须出现，每项包含 title 和 contentSummary，仅截图项包含 operation。基础信息：{json.dumps(payload.get('profile') or {}, ensure_ascii=False)}
组件树：{json.dumps(tree, ensure_ascii=False)}'''
    screenshot_nodes = [node for node in payload.get("nodes") or [] if node.get("type") == "screenshot" and node.get("image")]
    prompt += "\n附图顺序与组件 ID 对应：" + json.dumps([node.get("id") for node in screenshot_nodes], ensure_ascii=False)
    result = await call_model(prompt, config, [node["image"] for node in screenshot_nodes])
    data = parse_json_object(result)
    if not isinstance(data.get("nodes"), dict) or not isinstance(data.get("screenshots"), dict):
        raise HTTPException(status_code=502, detail="AI 未返回完整手册结构")
    expected = {str(node.get("id")): node for node in payload.get("nodes") or []}
    for node_id, node in expected.items():
        bucket = "screenshots" if node.get("type") in ("screenshot", "screenshot-group") else "nodes"
        item = data[bucket].get(node_id)
        if not isinstance(item, dict) or not item.get("contentSummary") or (bucket == "screenshots" and not item.get("operation")):
            raise HTTPException(status_code=502, detail=f"AI 未生成完整组件文本：{node.get('name', node_id)}")
        item["contentSummary"] = str(item["contentSummary"]).strip()
        item["title"] = str(item.get("title") or node.get("name") or f"{node.get('type', '组件')}功能").strip()
        if bucket == "screenshots":
            item["operation"] = screenshot_operation(item["operation"])
        else:
            item.pop("operation", None)
    return {"nodes": data["nodes"], "screenshots": data["screenshots"], "status": "completed"}


@app.post("/generate-restructured")
async def generate_restructured(payload: Dict[str, Any]):
    """第二阶段：将第一阶段的组件文案整理成完整、去重的手册 JSON。"""
    nodes = payload.get("nodes") or []
    generated = payload.get("generated") or {}
    source = {
        "nodes": {node_id: {key: value for key, value in item.items() if key != "operation"}
                  for node_id, item in (generated.get("nodes") or {}).items() if isinstance(item, dict)},
        "screenshots": generated.get("screenshots") or {},
    }
    data: Dict[str, Any] = {}
    try:
        config = settings(payload)
    except HTTPException:
        config = None
    if config:
        prompt = f'''你是软件著作权操作手册总编。请将第一阶段生成的组件文案重构为真实软著操作手册 JSON。
保留所有组件 ID、父子层级和画布从上到下的顺序；父组件后紧跟子组件。只依据输入事实，不新增功能。
去重规则必须严格执行：
1. 非截图组件的 contentSummary 只能保留本组件相对于全部父级新增的内容。父级已经说明过的目标、范围、功能、对象、流程、字段或业务作用，一律从子组件删除，不得改写后重复表达。
2. 父级只写本级职责、范围和组织关系，不提前展开子组件细节；子级只写父级未涉及的具体功能。按文档顺序检查，同级组件也不得重复之前组件已经写过的内容。
3. 截图项只能保留 title 和 operation，禁止输出 contentSummary、界面概述、功能简介或任何非操作文字。operation 只保留与截图中可执行操作、按钮、字段、列表、图表和结果有关的说明。
4. 对无法写出新增内容的非截图组件，contentSummary 输出空字符串；不能为了填充内容重复父级说明。
JSON 中非截图项必须有 title、contentSummary；截图项必须有 title、operation，不能包含 contentSummary。title 为空时根据组件素材或截图可见主体补齐。
截图 operation 必须逐项说明图片中可辨认的按钮、字段、列表、图表、菜单、筛选及分页控件的实际功能和操作结果；不要编造图片无法证实的内容。
只返回 JSON：{{"nodes":{{...}},"screenshots":{{...}}}}。
基础信息：{json.dumps(payload.get('profile') or {}, ensure_ascii=False)}
组件树：{json.dumps(payload.get('tree') or [], ensure_ascii=False)}
第一阶段文案：{json.dumps(source, ensure_ascii=False)}'''
        try:
            data = parse_json_object(await call_model(prompt, config))
        except HTTPException:
            data = {}
    result = {"nodes": {}, "screenshots": {}, "status": "completed"}
    emitted_summaries: List[str] = []
    for node in restructure_node_order(nodes, payload.get("tree") or []):
        node_id = str(node.get("id"))
        bucket = "screenshots" if node.get("type") in ("screenshot", "screenshot-group") else "nodes"
        item = (data.get(bucket) or {}).get(node_id) or (source.get(bucket) or {}).get(node_id) or {}
        item = dict(item) if isinstance(item, dict) else {}
        fallback = node.get("name") or ("功能操作界面" if bucket == "screenshots" else "未命名组件")
        item["title"] = str(item.get("title") or fallback).strip()
        if bucket == "screenshots":
            item.pop("contentSummary", None)
            item["operation"] = screenshot_operation(item.get("operation") or (source.get(bucket) or {}).get(node_id, {}).get("operation"))
        else:
            item.pop("operation", None)
            item["contentSummary"] = unique_sentences(item.get("contentSummary"), emitted_summaries)
            if item["contentSummary"]:
                emitted_summaries.append(item["contentSummary"])
        result[bucket][node_id] = item
    return result


@app.post("/generate-manual")
async def generate_manual(payload: Dict[str, Any]):
    """兼容旧调用方；新前端使用 generate-component 以支持暂停和续生成。"""
    config = settings(payload)
    nodes = payload.get("nodes") or []
    by_id = {node.get("id"): node for node in nodes}
    result: Dict[str, Any] = {"screenshots": {}, "nodes": {}, "status": "completed"}
    for node in [item for item in nodes if item.get("type") == "screenshot"] + [item for level in ("page", "module", "system") for item in nodes if item.get("type") == level]:
        children = []
        for child_id in node.get("children") or []:
            child = by_id.get(child_id) if isinstance(child_id, str) else child_id
            if child:
                generated = result["screenshots" if child.get("type") == "screenshot" else "nodes"].get(child.get("id"))
                if generated:
                    children.append({"name": child.get("name"), "generated": generated})
        generated = await generate_component({**payload, "node": node, "children": children, "settings": payload.get("settings") or {}})
        result["screenshots" if node.get("type") == "screenshot" else "nodes"][node.get("id")] = generated
    return result


async def call_model(prompt: str, config: AiSettings, images: Any = None) -> str:
    if isinstance(images, str):
        images = [images] if images else []
    images = [item for item in (images or []) if isinstance(item, str) and item.startswith("data:image/")]
    endpoint = (config.endpoint or os.getenv("MODEL_ENDPOINT", "")).rstrip("/")
    endpoint_path = urlsplit(endpoint).path
    is_responses_url = endpoint_path.endswith(("/response", "/responses"))
    is_chat_url = endpoint_path.endswith("/chat/completions")
    mode = "response" if is_responses_url else "chat" if is_chat_url else config.mode
    expected_path = "/response" if mode == "response" else "/chat/completions"
    has_complete_path = is_responses_url or is_chat_url
    urls = [endpoint if has_complete_path else endpoint + expected_path]
    if mode == "response" and not has_complete_path:
        alternate_path = "/responses" if expected_path == "/response" else "/response"
        urls.append(endpoint + alternate_path)
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    if mode == "response":
        content: List[Dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for image in images:
            content.append({"type": "input_image", "image_url": image})
        body = {"model": config.model, "input": [{"role": "user", "content": content}]}
    else:
        content = [{"type": "text", "text": prompt}]
        for image in images:
            content.append({"type": "image_url", "image_url": {"url": image}})
        body = {"model": config.model, "messages": [{"role": "user", "content": content}], "temperature": 0.4}
    attempted_urls: List[str] = []
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            for url in urls:
                attempted_urls.append(url)
                response = await client.post(url, json=body, headers=headers)
                if response.status_code >= 400:
                    if response.status_code in (404, 501) and url != urls[-1]:
                        continue
                    response.raise_for_status()
                data = response.json()
                break
    except httpx.HTTPStatusError as error:
        response_text = error.response.text.strip().replace("\n", " ")[:300]
        detail = f"模型接口返回 {error.response.status_code}：{url}"
        if len(attempted_urls) > 1:
            detail += f"；已尝试：{', '.join(attempted_urls)}"
        if response_text:
            detail += f"；{response_text}"
        raise HTTPException(status_code=502, detail=detail) from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail=f"模型接口调用失败：{url}；{error}") from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"模型服务响应失败：{error}") from error
    if data.get("output_text"):
        return data["output_text"]
    choices = data.get("choices") or []
    if choices:
        content = choices[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
        return content
    output = data.get("output") or []
    return "\n".join(part.get("text", "") for item in output for part in (item.get("content") or []) if isinstance(part, dict))


def parse_pair(value: str) -> Dict[str, str]:
    result = {"contentSummary": "", "operation": ""}
    current = None
    for line in (value or "").splitlines():
        match = re.match(r"^\s*(title|标题|contentSummary|内容简介|operation|操作介绍|操作说明)\s*[:：]\s*(.*)$", line, re.IGNORECASE)
        if match:
            current = "title" if match[1].lower() in ("title", "标题") else "contentSummary" if match[1].lower() in ("contentsummary", "内容简介") else "operation"
            result[current] = match[2].strip()
        elif current:
            result[current] += "\n" + line.strip()
    return {key: value.strip() for key, value in result.items()}


def parse_json_object(value: str) -> Dict[str, Any]:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", value or ""):
        try:
            data, _ = decoder.raw_decode(value[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def parse_optimized_text(value: str) -> str:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", value or ""):
        try:
            data, _ = decoder.raw_decode(value[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("optimized_text"), str):
            return data["optimized_text"].strip()
    return ""
