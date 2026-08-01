"""autotrader — a multi-region systematic trading research engine.

This package backtests and paper-trades long-term and short-term strategies
across regional equity markets, with region-correct costs, taxes, settlement
rules and trading calendars.

It does **not** guarantee profits, and it does not connect to a broker. See the
README for what is and is not claimed.
"""

from .core.instrument import AssetClass, Instrument
from .core.market import CHINA, INDIA, RUSSIA, UNITED_STATES, MarketSpec, get_market
from .core.money import FXRates, Money
from .data.bars import Bar, BarSeries, MarketDataSet
from .engine.backtest import BacktestConfig, BacktestEngine
from .engine.metrics import PerformanceReport, RoundTrip
from .execution.orders import Horizon, Order, Side
from .portfolio.portfolio import Portfolio
from .portfolio.sizing import SizingConfig
from .risk.limits import RiskConfig, RiskManager
from .strategy.long_term import LongTermConfig, LongTermStrategy
from .strategy.short_term import ShortTermConfig, ShortTermStrategy

__version__ = "0.1.0"

__all__ = [
    "AssetClass",
    "Bar",
    "BarSeries",
    "BacktestConfig",
    "BacktestEngine",
    "CHINA",
    "FXRates",
    "Horizon",
    "INDIA",
    "Instrument",
    "LongTermConfig",
    "LongTermStrategy",
    "MarketDataSet",
    "MarketSpec",
    "Money",
    "Order",
    "PerformanceReport",
    "Portfolio",
    "RUSSIA",
    "RiskConfig",
    "RiskManager",
    "RoundTrip",
    "ShortTermConfig",
    "ShortTermStrategy",
    "Side",
    "SizingConfig",
    "UNITED_STATES",
    "get_market",
    "__version__",
]
