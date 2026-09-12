"""D03 练习：工具白名单与统一执行入口（目前只有要求，尚未实现）。

前置小修：tool_params.py 的案例统计尚未使用 expected。
请让实际通过/拒绝与 expected 比较，再统计符合预期的数量。

一、导入
    从 stock_agent.tools.company 导入 get_company_profile。
    从 stock_agent.tools.quote 导入 get_quote。
    从 stock_agent.schemas.tool_params 导入 CompanyToolParams。

二、定义白名单 TOOL_REGISTRY
    用字典保存两个工具，以工具名称字符串作为键。
    每项再用字典保存 handler（函数对象）和 params_model（参数模型类）。
    键名为 get_company_profile、get_quote。
    注意：保存函数对象，不加调用括号；两个工具共用 CompanyToolParams。

三、实现 execute_tool(tool_name: str, arguments: dict) -> dict
    1. 检查名称是否在白名单中；未知名称抛出 ValueError，不能执行任何工具。
    2. 取出对应的参数模型，用 model_validate(arguments) 校验。
    3. 校验成功后，用校验对象中的 company_id 调用 handler。
       不要把原始 arguments 直接传入，否则会丢失去除空白等处理。
    4. 返回工具结果。参数错误的 ValidationError、工具的 ValueError 暂时向外传播，
       在演示代码中捕获；后续 Agent 循环再统一转换为工具错误结果。
    不使用 eval、exec 或根据任意字符串动态导入函数。

四、在 __main__ 中验证
    get_quote + {"company_id": "NVDA"} -> 返回 fixture 报价。
    get_company_profile + {"company_id": "NVDA"} -> 返回 fixture 公司资料。
    get_quote + {"company_id": "  NVDA  "} -> 通过（确认使用清理后的参数）。
    delete_file + {"company_id": "NVDA"} -> ValueError，未知工具。
    get_quote + {"company_id": ""} -> ValidationError，不执行工具。
    get_quote + {"company_id": "NVDA", "extra": 1} -> ValidationError。
    get_quote + {"company_id": "AAPL"} -> 参数格式通过，但工具抛出 ValueError。
    对比实际结果与预期，不要把所有异常都当成通过。

五、运行
    从项目根目录、已激活的虚拟环境执行：
        PYTHONPATH=backend/src python -m stock_agent.tools.registry
    这只为本次命令指定包查找目录，不会永久修改终端环境。
    本练习不调用模型；下一步再解析模型返回的 JSON 参数。
"""

# TODO：导入函数及参数模型。
from stock_agent.tools.company import get_company_profile
from stock_agent.tools.quote import get_quote
from stock_agent.schemas.tool_params import CompanyToolParams
from collections.abc import Callable

# TODO：定义 TOOL_REGISTRY。
TOOL_REGISTRY = {
    "get_company_profile": {
        # handler（函数对象）和 params_model（参数模型类）
        "handler": get_company_profile,
        "params_model": CompanyToolParams,
    },
    "get_quote": {
        "handler": get_quote,
        "params_model": CompanyToolParams,
    }
}

# TODO：实现 execute_tool。
def execute_tool(
    tool_name: str,
    arguments: dict,
    before_execute: Callable[[], None] | None = None,
) -> dict:
    """校验通过后通知调用方计数，再启动工具 handler。"""
    if tool_name not in TOOL_REGISTRY:
        raise ValueError(f"未知工具：{tool_name}")
    tool = TOOL_REGISTRY[tool_name]
    request = tool["params_model"].model_validate(arguments)
    if before_execute is not None:
        before_execute()
    return tool["handler"](request.company_id)
