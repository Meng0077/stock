from longbridge.openapi import (
    Config,
    QuoteContext,
)

from stock_agent.market.longbridge.longbridge_provider import (
    LongbridgeMarketDataProvider,
)

def build_longbridge_market_provider(
) -> LongbridgeMarketDataProvider:
    """组装完整的 Longbridge MarketDataProvider。"""

    config = Config.from_apikey_env()

    return LongbridgeMarketDataProvider(quote_context=QuoteContext(config))
