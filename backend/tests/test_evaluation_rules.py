"""D05 离线验收：检查真实执行事件、保存结果和检查器的反例。"""

import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from stock_agent.tools import registry


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "evals" / "run_basic_cases.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("d05_runner_test", RUNNER_PATH)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


@pytest.fixture
def runner():
    return load_runner()


@pytest.fixture
def case_map(runner):
    return {case["case_id"]: case for case in runner.load_cases(runner.DEFAULT_DATASET)}


def test_ten_cases_run_through_agent_with_expected_safety_behavior(runner, case_map):
    agent = runner.load_agent()
    original_handlers = {name: item["handler"] for name, item in registry.TOOL_REGISTRY.items()}
    records = asyncio.run(runner.run_selected(list(case_map.values()), "offline", agent))
    assert len(records) == 10
    assert len({record["run_id"] for record in records}) == 10
    assert all(record["automatic_verdict"] == "pass" for record in records)
    assert all(record["human_review"]["verdict"] == "pending" for record in records)
    assert all(record["execution_mode"] == "offline" for record in records)
    assert all(record["usage"] is None for record in records)
    assert all(record["versions"]["model"] == "scripted" for record in records)
    assert {name: item["handler"] for name, item in registry.TOOL_REGISTRY.items()} == original_handlers

    by_id = {record["case_id"]: record for record in records}
    assert by_id["D05-06"]["handler_call_count"] == 0
    assert by_id["D05-06"]["events"][1]["code"] == "invalid_arguments"
    assert by_id["D05-07"]["handler_call_count"] == 0
    assert by_id["D05-07"]["events"][1]["code"] == "unknown_tool"
    assert by_id["D05-08"]["handler_call_count"] == 1
    assert by_id["D05-08"]["events"][1]["code"] == "tool_timeout"
    assert by_id["D05-08"]["tool_execution_count"] == 1
    assert by_id["D05-09"]["terminal_status"] == "invalid_evidence"
    assert by_id["D05-09"]["safe_error"]["code"] == "invalid_evidence"
    assert by_id["D05-10"]["terminal_status"] == "budget_exhausted"
    assert by_id["D05-10"]["model_request_count"] == agent.MAX_MODEL_ROUNDS
    assert by_id["D05-10"]["tool_execution_count"] == 2
    quote = next(
        event for event in by_id["D05-02"]["events"]
        if event["type"] == "tool_succeeded"
    )
    assert quote["fixture_result"]["data_mode"] == "fixture"
    assert quote["evidence_id"] == "E1"
    assert by_id["D05-02"]["final_output"]["data_mode"] == "fixture"


def test_checker_rejects_bad_evidence_ids_fixture_and_tool_ids(runner, case_map):
    agent = runner.load_agent()
    good = asyncio.run(runner.run_case(case_map["D05-02"], "offline", agent))
    assert runner.check_record(good, case_map["D05-02"]["expected"]) == []

    bad_evidence = deepcopy(good)
    bad_evidence["final_output"]["facts"][0]["evidence_ids"] = ["E99"]
    assert "invalid_evidence" in runner.check_record(bad_evidence)

    bad_mode = deepcopy(good)
    bad_mode["final_output"]["data_mode"] = "live"
    assert "data_mode_mismatch" in runner.check_record(bad_mode)

    bad_fixture = deepcopy(good)
    next(event for event in bad_fixture["events"] if event["type"] == "tool_succeeded")["fixture_result"]["data_mode"] = "live"
    assert "fixture_mismatch" in runner.check_record(bad_fixture)

    bad_call_id = deepcopy(good)
    next(event for event in bad_call_id["events"] if event["type"] == "tool_succeeded")["tool_call_id"] = "different"
    assert "tool_call_id_mismatch" in runner.check_record(bad_call_id)

    bad_budget = deepcopy(good)
    bad_budget["model_request_count"] = 999
    assert "model_budget" in runner.check_record(bad_budget)

    missing_output = deepcopy(good)
    missing_output["final_output"] = None
    assert "missing_final_output" in runner.check_record(missing_output)


def test_checker_rejects_unsafe_terminal_error(runner, case_map):
    record = asyncio.run(runner.run_case(case_map["D05-09"], "offline", runner.load_agent()))
    bad = deepcopy(record)
    bad["events"][-1]["error"]["message"] = "PRIVATE_API_KEY"
    bad["safe_error"]["message"] = "PRIVATE_API_KEY"
    assert "unsafe_error" in runner.check_record(bad)


def test_results_are_unique_and_keep_snapshots_without_unknown_usage_as_zero(runner, case_map, tmp_path):
    record = asyncio.run(runner.run_case(case_map["D05-01"], "offline", runner.load_agent()))
    first = runner.save_records([record], tmp_path, "offline")
    second = runner.save_records([record], tmp_path, "offline")
    assert first != second
    assert first.exists() and second.exists()
    saved = json.loads(first.read_text(encoding="utf-8"))
    assert saved["input_snapshot"] == case_map["D05-01"]["input"]
    assert saved["usage"] is None
    assert saved["human_review"]["verdict"] == "pending"
    assert saved["versions"]["code"]
    assert len(saved["versions"]["source_sha256"]) == 64
    assert saved["messages"][1]["role"] == "user"
    assert "PRIVATE_API_KEY" not in first.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "contents, message",
    [
        ('{"case_id":"A","input":{},"expected":{},"scripted_responses":[]}\n'
         '{"case_id":"A","input":{},"expected":{},"scripted_responses":[]}', "重复"),
        ('{"case_id":', "第 1 行"),
    ],
)
def test_dataset_rejects_duplicate_ids_and_bad_json(runner, tmp_path, contents, message):
    path = tmp_path / "cases.jsonl"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        runner.load_cases(path)


def test_unprepared_case_and_real_mode_without_credentials_are_blocked(runner, case_map):
    agent = runner.load_agent()
    unprepared = deepcopy(case_map["D05-01"])
    unprepared["scripted_responses"] = []
    unprepared["preparation_status"] = "todo"
    offline = asyncio.run(runner.run_case(unprepared, "offline", agent))
    real = asyncio.run(runner.run_case(case_map["D05-02"], "real", agent))
    assert offline["automatic_verdict"] == "blocked"
    assert real["automatic_verdict"] == "blocked"
    assert offline["model_request_count"] == real["model_request_count"] == 0


def test_real_mode_path_reuses_agent_and_closes_client_without_network(runner, case_map):
    agent = runner.load_agent()
    closed = []

    class FakeRealClient:
        def __init__(self, **kwargs):
            self.scripted = runner.ScriptedClient(case_map["D05-02"]["scripted_responses"])

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            closed.append(True)

        async def create(self, **kwargs):
            return await self.scripted.create(**kwargs)

    agent.LLMClient = FakeRealClient
    record = asyncio.run(runner.run_case(
        case_map["D05-02"],
        "real",
        agent,
        api_key="fake-key",
        model="offline-model",
        provider="deepseek",
    ))
    assert record["automatic_verdict"] == "pass"
    assert record["model_request_count"] == 2
    assert record["handler_call_count"] is None
    assert closed == [True]


def test_cancellation_propagates_and_restores_tool_handlers(runner, case_map):
    agent = runner.load_agent()
    original = registry.TOOL_REGISTRY["get_quote"]["handler"]

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError

    agent.model_loop = cancelled
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runner.run_case(case_map["D05-02"], "offline", agent))
    assert registry.TOOL_REGISTRY["get_quote"]["handler"] is original
