"""报价工具练习：价格完全虚构，不代表 NVDA 的真实或历史行情。"""

from stock_agent.tools.errors import UnsupportedCompanyError

QUOTE = {
    "company_id": "NVDA",
    "price": 100.00,
    "currency": "USD",
    "quoted_at": "2026-09-11T09:00:00+08:00",
    "data_mode": "fixture",
    "source": "本地教学模拟数据",
    "note": "固定虚构报价，仅用于验证工具调用；报价时间也是预设的教学时间。",
}

# TODO：你来实现 get_quote(company_id: str) -> dict。
# 仅支持 NVDA；其他标识抛出 ValueError。
# 返回字典副本（QUOTE.copy()），避免调用者修改这份固定数据。
def get_quote(company_id: str) -> dict:
    if company_id != "NVDA":
        raise UnsupportedCompanyError(f"不支持的公司标识：{company_id}")
    return QUOTE.copy()

if __name__ == "__main__":
    try:
        quote = get_quote("NVDA")
        print("报价查询成功：")
        for k, v in quote.items():
            print(f"  {k}: {v}")
    except ValueError as e:
        print(f"查询失败：{e}")
        
