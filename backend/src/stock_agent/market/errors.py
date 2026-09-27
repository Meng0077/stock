class MarketDataProviderError(RuntimeError):
    """行情供应商请求失败。"""


class MarketDataCapabilityError(MarketDataProviderError):
    """行情供应商不支持或未配置请求的数据能力。"""
