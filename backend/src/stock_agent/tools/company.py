"""公司资料工具练习：以下为本地教学数据，不是实时查询结果。"""

from stock_agent.tools.errors import UnsupportedCompanyError

COMPANY_PROFILE = {
    "company_id": "NVDA",
    "company_name": "NVIDIA（英伟达）",
    "description": "教学用简化公司介绍：提供 GPU 及相关计算平台，用于图形处理和人工智能计算。",
    "data_mode": "fixture",
    "source": "本地教学模拟数据",
    "as_of": "2026-09-11T09:00:00+08:00",
}

# TODO：你来实现 get_company_profile(company_id: str) -> dict。
# 仅支持 NVDA；其他标识抛出 ValueError。
# 返回字典副本（COMPANY_PROFILE.copy()），避免调用者修改这份固定数据。
def get_company_profile(company_id: str) -> dict:
    if company_id != "NVDA":
        raise UnsupportedCompanyError(f"不支持的公司标识：{company_id}")
    return COMPANY_PROFILE.copy()

if __name__ == "__main__":
    # 测试 get_company_profile() 函数
    try:
        profile = get_company_profile("NVDA")
        print("公司资料查询成功：")
        for k, v in profile.items():
            print(f"  {k}: {v}")
    except ValueError as e:
        print(f"查询失败：{e}")
