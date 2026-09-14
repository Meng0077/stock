"""预览必须在读取密钥或创建模型客户端之前结束。"""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest


def test_preview_is_offline_and_shows_request_contract(monkeypatch, capsys):
    module_path = Path(__file__).parents[1] / "examples" / "structured_agent.py"
    spec = importlib.util.spec_from_file_location("structured_agent_preview", module_path)
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)

    def unexpected_call(*args, **kwargs):
        pytest.fail("--preview 不应读取 .env 或创建模型客户端")

    monkeypatch.setattr(agent, "load_dotenv", unexpected_call)
    monkeypatch.setattr(agent, "BigModelAsyncClient", unexpected_call)
    monkeypatch.setenv("ZHIPU_API_KEY", "PREVIEW_TEST_SECRET")

    assert asyncio.run(agent.main(["--preview"])) == 0

    preview = json.loads(capsys.readouterr().out)
    assert preview["response_format"] == {"type": "json_object"}
    assert preview["research_output_schema"]["title"] == "ResearchOutput"
    assert {tool["function"]["name"] for tool in preview["tools"]} == {
        "get_company_profile", "get_quote"
    }
    assert preview["messages"][0]["role"] == "system"
    assert "PREVIEW_TEST_SECRET" not in json.dumps(preview)
