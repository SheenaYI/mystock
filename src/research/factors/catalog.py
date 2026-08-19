"""Frozen technical factor catalogue used by the research selector.

Market-state variables are deliberately not listed here: they describe the
environment in which a stock factor is evaluated, rather than being stock
features themselves.
"""

from __future__ import annotations


BASE_FACTORS = (
    "return_5", "return_20", "return_60", "ma_gap_20", "volatility_20",
    "volume_ratio_20", "intraday_range",
)

FACTOR_CATEGORIES: dict[str, str] = {
    # Trend and momentum
    "return_5": "trend", "return_20": "trend", "return_60": "trend",
    "ma_gap_20": "trend", "return_120": "trend",
    "trend_efficiency_60": "trend", "vol_adjusted_return_60": "trend",
    # Price shape and reversal
    "return_1": "price", "reversal_5": "price", "ma_gap_5": "price",
    "high_low_position_60": "price", "return_skewness_20": "price",
    # Risk and volatility
    "volatility_20": "risk", "downside_volatility_20": "risk",
    "drawdown_60": "risk", "intraday_range": "risk",
    # Volume and liquidity
    "volume_ratio_20": "liquidity", "volume_trend_20": "liquidity",
    "volume_price_corr_20": "liquidity", "illiquidity_20": "liquidity",
    # Relative / cross-sectional strength
    "beta_60": "relative", "market_corr_60": "relative",
    "idiosyncratic_return_20": "relative", "idiosyncratic_return_60": "relative",
    "residual_volatility_60": "relative",
}

# Short, deterministic factor cards give the selector an auditable common
# vocabulary. They describe what a factor measures, not a promise of return.
FACTOR_ECONOMIC_MEANINGS: dict[str, str] = {
    "return_1": "上一日的极短期价格变化，捕捉短期反转或延续。",
    "return_5": "过去五日的短期动量，反映近期相对强弱。",
    "return_20": "过去二十日的中短期动量，反映一个月左右的相对趋势。",
    "return_60": "过去六十日的中期动量，反映较稳定的趋势强弱。",
    "return_120": "过去一百二十日的较长期动量，反映更慢的趋势延续。",
    "reversal_5": "五日收益的反向刻画，检验短期过度反应后的回撤。",
    "ma_gap_5": "价格相对五日均线的偏离，反映短期趋势或均值回归压力。",
    "ma_gap_20": "价格相对二十日均线的偏离，反映中短期趋势位置。",
    "high_low_position_60": "价格在六十日高低区间的位置，反映突破或超买超卖位置。",
    "return_skewness_20": "二十日收益分布的偏度，反映上涨与下跌尾部的不对称性。",
    "trend_efficiency_60": "六十日净趋势相对路径波动的效率，区分平滑趋势和来回震荡。",
    "vol_adjusted_return_60": "经自身波动率调整的六十日收益，比较趋势强度而非单纯高波动。",
    "volatility_20": "二十日总波动率，反映近期风险与不确定性。",
    "downside_volatility_20": "二十日下行波动率，强调亏损方向的风险。",
    "drawdown_60": "相对六十日高点的回撤，反映价格压力和修复空间。",
    "intraday_range": "日内高低价区间，反映单日交易波动与不确定性。",
    "volume_ratio_20": "当前成交量相对二十日均量，反映交易活跃度是否异常。",
    "volume_trend_20": "成交量的二十日趋势，反映关注度或流动性在扩张还是收缩。",
    "volume_price_corr_20": "二十日量价联动，反映价格变化是否得到成交量确认。",
    "illiquidity_20": "单位成交额对应的价格变动，反映流动性不足与冲击成本风险。",
    "beta_60": "相对沪深300的六十日系统性敏感度，反映市场暴露。",
    "market_corr_60": "与沪深300六十日收益相关性，反映个股跟随大盘的程度。",
    "idiosyncratic_return_20": "剔除市场共同变动后的二十日个股收益，反映特质强弱。",
    "idiosyncratic_return_60": "剔除市场共同变动后的六十日个股收益，反映中期特质强弱。",
    "residual_volatility_60": "剔除市场共同变动后的六十日残差波动，反映特质风险。",
}

TECHNICAL_FACTOR_MENU = tuple(FACTOR_CATEGORIES)
CANDIDATE_FACTORS = tuple(factor for factor in TECHNICAL_FACTOR_MENU if factor not in BASE_FACTORS)

if set(FACTOR_ECONOMIC_MEANINGS) != set(FACTOR_CATEGORIES):
    raise RuntimeError("every registered technical factor needs one economic-meaning card")


def factor_category(name: str) -> str:
    """Return the frozen family name, failing rather than guessing."""
    try:
        return FACTOR_CATEGORIES[name]
    except KeyError as exc:
        raise ValueError(f"unregistered technical factor: {name}") from exc
