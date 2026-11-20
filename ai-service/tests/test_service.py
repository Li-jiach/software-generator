import asyncio
import json
import sys
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as service


def test_retrieval_returns_relevant_source_and_no_unrelated_text():
    sources = [service.Source(id="a", name="材料要求", text="源程序前后各30页，程序每页不少于50行。"),
               service.Source(id="b", name="午餐", text="餐厅今日提供咖啡和面包。")]
    hits = service.retrieve("源程序每页多少行", sources)
    assert hits and hits[0]["id"] == "a"
    assert all(hit["id"] != "b" for hit in hits)


def test_config_masks_key_and_preserves_it_when_blank(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setenv("SERVICE_TOKEN", "test-token")
    client = TestClient(service.app)
    assert client.get("/config").status_code == 401
    headers = {"X-Service-Token": "test-token"}
    r = client.put("/config", headers=headers, json={"base_url": "http://localhost:9000/v1", "model": "local", "api_key": "secret"})
    assert r.status_code == 200 and r.json()["api_key_set"]
    assert "secret" not in r.text and "api_key" not in r.json()
    client.put("/config", headers=headers, json={"model": "local-v2"})
    assert service.read_config().api_key == "secret"
    assert (service.CONFIG_PATH.stat().st_mode & 0o777) == 0o600
    client.put("/config", headers=headers, json={"clear_api_key": True})
    assert not service.read_config().api_key


def test_chat_completion_payload_and_actual_provider_response():
    seen = {}
    def handler(request):
        seen.update(json.loads(request.content))
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": "测试模型的实际回答"}}], "usage": {"total_tokens": 12}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await service.call_model(service.ModelConfig(base_url="http://model/v1", api_key="test-key", model="test", reasoning_effort="high"), [{"role": "user", "content": "问题"}], client)
    answer, usage = asyncio.run(run())
    assert answer == "测试模型的实际回答"
    assert seen["reasoning_effort"] == "high" and seen["stream"] is False
    assert usage["total_tokens"] == 12


def test_default_effort_is_omitted_for_compatible_models():
    def handler(request):
        assert "reasoning_effort" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await service.call_model(service.ModelConfig(base_url="http://model/v1/chat/completions", model="test"), [], client)
    assert asyncio.run(run())[0] == "ok"


def test_missing_model_stops_before_retrieval(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.setenv("SERVICE_TOKEN", "test-token")
    monkeypatch.setattr(service, 'local_sources', lambda: (_ for _ in ()).throw(AssertionError('retrieval started')))
    client = TestClient(service.app)
    for endpoint, body in [('/agent/step', {'question': '多少行？'}),
                           ('/chat', {'question': '多少行？', 'query': '源程序行数'})]:
        assert client.post(endpoint, headers={'X-Service-Token': 'test-token'}, json=body).status_code == 409


def test_model_rewrites_follow_up_before_retrieval(monkeypatch):
    config = service.ModelConfig(base_url='http://model/v1', model='configured')
    monkeypatch.setattr(service, 'read_config', lambda: config)
    monkeypatch.setenv('SERVICE_TOKEN', 'test-token')
    responses = iter(['{"action":"knowledge","args":{"query":"源程序每页行数"}}', '不少于50行。[1]',
                      '{"action":"knowledge","args":{"query":" "}}'])
    called = []

    async def model(config_used, messages):
        assert config_used is config
        called.append(messages)
        return next(responses), {}

    monkeypatch.setattr(service, 'call_model', model)
    monkeypatch.setattr(service, 'local_sources', lambda: [service.Source(id='rule', name='规范', text='源程序每页不少于50行。')])
    client = TestClient(service.app, headers={'X-Service-Token': 'test-token'})
    body = {'question': '那每页呢？', 'history': [{'role': 'user', 'content': '源程序要求'}]}
    plan = client.post('/agent/step', json=body)
    assert len(called) == 1 and '源程序要求' in called[0][-1]['content']
    answer = client.post('/chat', json={**body, **plan.json()['args']})
    assert answer.json()['sources'][0]['id'] == 'rule' and '50行' in called[1][0]['content']
    assert client.post('/agent/step', json=body).status_code == 502
