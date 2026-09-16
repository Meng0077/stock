"""D08：在固定 D05 案例上离线对照 Manual Agent 与 LangChain Agent。

运行目标命令（完成 TODO 后）：
    PYTHONPATH=backend/src backend/.venv/bin/python evals/run_agent_comparison.py

默认只使用 scripted responses 和 fixture，不读取 API Key，不访问网络。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from stock_agent.agents.comparison import CaseComparison


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evals" / "basic_cases.jsonl"
DEFAULT_REPORT = ROOT / "docs" / "day08" / "report.md"


def load_comparison_cases(path: Path) -> list[dict[str, Any]]:
    """输入 D05 JSONL 路径；输出 D08 选中的四个原始案例。"""
    # TODO D08-Step-2.2：复用 D05 loader 和 select_comparison_cases()。
    raise NotImplementedError


async def run_manual_case(case: dict[str, Any]):
    """输入一个 D05 案例；离线运行 Manual Agent；输出 AgentObservation。"""
    # TODO D08-Step-3.2：复用 D05 scripted runner，不复制 Manual model_loop。
    raise NotImplementedError


async def run_langchain_case(case: dict[str, Any]):
    """输入同一 D05 案例；用 fake model 运行 LangChain；输出 AgentObservation。"""
    # TODO D08-Step-4.2：把 scripted responses 转成 AIMessage；设置有限 recursion_limit。
    # TODO D08-Step-4.3：统计模型请求和 handler 执行；捕获现有异常但不修复。
    raise NotImplementedError


async def run_comparison(cases: list[dict[str, Any]]) -> list[CaseComparison]:
    """输入固定案例；逐例运行两种 Agent；输出一一对应的对照结果。"""
    # TODO D08-Step-5.2：同一案例先 Manual 后 LangChain，确保 handler 已恢复。
    raise NotImplementedError


def render_report(comparisons: list[CaseComparison]) -> str:
    """输入对照结果；输出不含密钥和完整模型对象的 Markdown 报告。"""
    # TODO D08-Step-6.1：生成案例表与职责边界表，不覆盖人工结论模板。
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """解析离线命令参数、运行四个案例并写报告；成功返回 0。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.parse_args(argv)
    # TODO D08-Step-6.2：执行 run_comparison()，安全写入报告并打印摘要。
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
