from typing import Final


# 这里只维护高频且语义相对稳定的证券别名。
#
# 目标不是覆盖所有自然语言表达，
# 而是让常见公司名称、中文名称和投资社区昵称
# 可以走确定性的 Target Resolution 路径。
#
# 规则：
# - value 使用 tuple，因为一个名称可能对应多个证券代码；
# - 人物名、产品名等依赖上下文的表达不放在这里；
# - 含义不够稳定的网络昵称交给后续 LLM semantic fallback。
SECURITY_ALIASES: Final[
    dict[str, tuple[str, ...]]
] = {
    # -----------------------------
    # Large Cap Technology
    # -----------------------------

    "英伟达": ("NVDA",),
    "辉达": ("NVDA",),
    "nvidia": ("NVDA",),
    "达子": ("NVDA",),

    "苹果": ("AAPL",),
    "苹果公司": ("AAPL",),
    "apple": ("AAPL",),
    "果子": ("AAPL",),

    "微软": ("MSFT",),
    "microsoft": ("MSFT",),

    "亚马逊": ("AMZN",),
    "amazon": ("AMZN",),

    "meta": ("META",),
    "facebook": ("META",),
    "脸书": ("META",),

    # Alphabet 存在两个常见上市 share class，
    # Resolver 不能在用户未说明时擅自选择。
    "谷歌": (
        "GOOG",
        "GOOGL",
    ),
    "google": (
        "GOOG",
        "GOOGL",
    ),
    "alphabet": (
        "GOOG",
        "GOOGL",
    ),

    "特斯拉": ("TSLA",),
    "tesla": ("TSLA",),

    "奈飞": ("NFLX",),
    "网飞": ("NFLX",),
    "netflix": ("NFLX",),

    # -----------------------------
    # Semiconductor
    # -----------------------------

    "超威": ("AMD",),
    "超威半导体": ("AMD",),
    "按摩店": ("AMD",),

    "英特尔": ("INTC",),
    "intel": ("INTC",),
    "牙膏厂": ("INTC",),

    "台积电": ("TSM",),
    "台积": ("TSM",),
    "tsmc": ("TSM",),

    "博通": ("AVGO",),
    "broadcom": ("AVGO",),

    "高通": ("QCOM",),
    "qualcomm": ("QCOM",),

    "美光": ("MU",),
    "micron": ("MU",),

    "阿斯麦": ("ASML",),
    "asml": ("ASML",),

    "超微电脑": ("SMCI",),
    "supermicro": ("SMCI",),
    "super micro": ("SMCI",),

    # -----------------------------
    # Software / Cloud / AI
    # -----------------------------

    "甲骨文": ("ORCL",),
    "oracle": ("ORCL",),

    "赛富时": ("CRM",),
    "salesforce": ("CRM",),

    "帕兰提尔": ("PLTR",),
    "palantir": ("PLTR",),

    "crowdstrike": ("CRWD",),

    "snowflake": ("SNOW",),

    "adobe": ("ADBE",),

    # -----------------------------
    # Finance / Crypto
    # -----------------------------

    "coinbase": ("COIN",),

    "robinhood": ("HOOD",),

    "摩根大通": ("JPM",),
    "小摩": ("JPM",),
    "jpmorgan": ("JPM",),
    "jp morgan": ("JPM",),

    "高盛": ("GS",),
    "goldman sachs": ("GS",),

    "美国银行": ("BAC",),
    "bank of america": ("BAC",),

    # -----------------------------
    # China ADR
    # -----------------------------

    "阿里巴巴": ("BABA",),
    "阿里": ("BABA",),
    "alibaba": ("BABA",),

    "拼多多": ("PDD",),
    "pdd holdings": ("PDD",),

    "京东": ("JD",),
    "jd.com": ("JD",),

    "百度": ("BIDU",),
    "baidu": ("BIDU",),

    "蔚来": ("NIO",),

    "小鹏": ("XPEV",),
    "小鹏汽车": ("XPEV",),
    "xpeng": ("XPEV",),

    "理想汽车": ("LI",),
    "li auto": ("LI",),

    "哔哩哔哩": ("BILI",),
    "b站": ("BILI",),
    "bilibili": ("BILI",),

    "网易": ("NTES",),
    "netease": ("NTES",),

    "携程": ("TCOM",),
    "trip.com": ("TCOM",),

    # -----------------------------
    # ETF
    # -----------------------------

    "半导体三倍多": ("SOXL",),
    "半导体3倍多": ("SOXL",),

    "纳指三倍多": ("TQQQ",),
    "纳指3倍多": ("TQQQ",),

    "纳指三倍空": ("SQQQ",),
    "纳指3倍空": ("SQQQ",),
}