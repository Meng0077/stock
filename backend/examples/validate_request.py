"""D02：每个案例同时显示预期和实际结果，全程离线。"""

from asyncio import sleep
import asyncio
from pathlib import Path
import sys

from pydantic import ValidationError

# 让直接运行教学脚本也能找到 src 包，无需先安装本地项目。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from stock_agent.schemas.research import ResearchRequest

VALID_INPUT = {
    "company_id": "NVDA",
    "question": "请概括本季度营收变化",
    "data_mode": "historical",
    "as_of": "2026-09-10T12:00:00+08:00",
}

async def change_question(request: ResearchRequest):
    print(f"原始问题：{request.question}")
    print("模拟等待 3 秒后清空问题字段")
    await sleep(3)
    try:
        request.question = "  "
    except ValidationError as error:
        print("清空问题字段被拒绝：")
        for item in error.errors(include_input=False, include_context=False, include_url=False):
            print(item)
            print(f"  拒绝：字段 {item['loc']}，错误类型 {item['type']}")
    else:
        print("清空问题字段被意外接受，请检查规则！")


async def main() -> int:
    missing = {k: v for k, v in VALID_INPUT.items() if k != "company_id"}
    # 元组：名称、输入、期望错误字段（None 表示应该成功）。
    cases = [
        ("正常输入", VALID_INPUT, None),
        ("清除首尾空白", {**VALID_INPUT, "question": "  分析营收  "}, None),
        ("缺少公司", missing, "company_id"),
        ("额外字段", {**VALID_INPUT, "api_key": "fake-example-only"}, "api_key"),
        ("非法日期", {**VALID_INPUT, "as_of": "2026-02-30T12:00:00+08:00"}, "as_of"),
        ("无时区", {**VALID_INPUT, "as_of": "2026-09-10T12:00:00"}, "as_of"),
        ("空问题", {**VALID_INPUT, "question": ""}, "question"),
        ("全空白问题", {**VALID_INPUT, "question": " \n\t "}, "question"),
        # question=None
        ("无问题", {**VALID_INPUT, "question": None }, "question"),
        ("问题过长", {**VALID_INPUT, "question": "问" * 2001}, "question"),
        ("非法资料模式", {**VALID_INPUT, "data_mode": "realtime"}, "data_mode"),
        ("空白公司", {**VALID_INPUT, "company_id": "   "}, "company_id"),
        ("公司标识过长", {**VALID_INPUT, "company_id": "A" * 81}, "company_id"),
        ("问题类型错误", {**VALID_INPUT, "question": 123}, "question"),
    ]
    passed = 0
    request = None
    for name, payload, expected_field in cases:
        print(f"\n{name}：预期{'通过' if expected_field is None else '拒绝'}")
        try:
            request = ResearchRequest.model_validate(payload)
        except ValidationError as error:
            errors = error.errors(include_input=False, include_context=False, include_url=False)
            for item in errors:
                print(item)
                print(f"  拒绝：字段 {item['loc']}，错误类型 {item['type']}")
            ok = expected_field is not None and any(
                item["loc"] == (expected_field,) for item in errors
            )
        else:
            print(f"  通过：{request.question}；时间类型 {type(request.as_of).__name__}")
            ok = expected_field is None
        passed += int(ok)
        if not ok:
            print("  与预期不符，请检查规则或案例！")
    
    assignment_ok =  await change_question(request)
            
    print(f"\n符合预期：{passed}/{len(cases)}")
    print("注意：historical/live 只是输入标签；校验通过不能证明资料真实或确为实时行情。")
    
    return 0 if passed == len(cases) and assignment_ok else 1


if __name__ == "__main__":
    asyncio.run(main())
    # raise SystemExit(main())
