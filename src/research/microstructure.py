"""Microstructure analytics toolkit -- spread, depth, slippage, basis decomposition.

What it does:
    Provides standard measures of market quality: quoted and effective spreads,
    slippage, order-book depth, price-impact coefficients, and basis breakdowns.
    All metrics follow Hasbrouck (2007) / O'Hara (1995) conventions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def quoted_spread_bps(bid: pd.Series, ask: pd.Series) -> pd.Series:
    """Quoted spread in basis points relative to midpoint."""
    mid = (bid + ask) / 2
    return ((ask - bid) / mid) * 10_000


def effective_spread_bps(price: pd.Series, mid: pd.Series) -> pd.Series:
    """Effective (realized) spread: 2 * |trade_price - mid| / mid, in bps."""
    return 2 * ((price - mid).abs() / mid) * 10_000


def signed_slippage_bps(
    price: pd.Series, mid: pd.Series, side: pd.Series | None = None
) -> pd.Series:
    """Signed slippage from mid in bps. Positive = adverse for the aggressor."""
    raw = ((price - mid) / mid) * 10_000
    if side is not None:
        raw = raw * side.map({"buy": 1, "sell": -1, "B": 1, "A": -1}).fillna(1)
    return raw


def realized_volatility(returns: pd.Series, annualize: float = 365.25 * 24) -> float:
    """Annualized realized volatility from return series."""
    if len(returns) < 2:
        return 0.0
    return float(returns.std() * np.sqrt(annualize))


def kyle_lambda(
    price_changes: pd.Series, signed_volume: pd.Series, min_obs: int = 30
) -> dict:
    """Kyle's lambda -- price impact coefficient.

    Regress: ΔP_t = λ * SignedVolume_t + ε_t
    λ measures permanent price impact per unit of signed order flow.
    """
    mask = price_changes.notna() & signed_volume.notna()
    dp = price_changes[mask].values
    sv = signed_volume[mask].values

    if len(dp) < min_obs:
        return {"lambda": np.nan, "t_stat": np.nan, "r_squared": np.nan, "n_obs": len(dp)}

    slope, intercept, r_value, p_value, std_err = stats.linregress(sv, dp)
    return {
        "lambda": slope,
        "t_stat": slope / std_err if std_err > 0 else np.nan,
        "r_squared": r_value ** 2,
        "p_value": p_value,
        "n_obs": len(dp),
    }


def amihud_illiquidity(
    returns: pd.Series, volume_usd: pd.Series, periods: int | None = None
) -> float:
    """Amihud (2002) illiquidity ratio: mean(|r_t| / volume_t).

    Higher = less liquid. Standard measure for cross-venue comparison.
    """
    if periods:
        returns = returns.iloc[-periods:]
        volume_usd = volume_usd.iloc[-periods:]

    mask = volume_usd > 0
    ratio = returns[mask].abs() / volume_usd[mask]
    return float(ratio.mean()) if len(ratio) > 0 else np.nan


def roll_spread(returns: pd.Series) -> float:
    """Roll (1984) implied spread from return autocovariance.

    S = 2 * sqrt(-Cov(r_t, r_{t-1})) if covariance is negative, else 0.
    """
    if len(returns) < 3:
        return 0.0
    cov = float(returns.autocorr(lag=1) * returns.var())
    return 2 * np.sqrt(-cov) if cov < 0 else 0.0


def basis_decomposition(
    perp_price: pd.Series,
    oracle_price: pd.Series,
    benchmark_price: pd.Series | None = None,
) -> pd.DataFrame:
    """Decompose perp-benchmark basis into oracle tracking error + perp premium.

    basis_total = perp - benchmark
    oracle_error = oracle - benchmark
    perp_premium = perp - oracle
    """
    result = pd.DataFrame(index=perp_price.index)
    result["perp"] = perp_price
    result["oracle"] = oracle_price

    if benchmark_price is not None:
        # Align by nearest timestamp
        benchmark_aligned = benchmark_price.reindex(perp_price.index, method="ffill")
        result["benchmark"] = benchmark_aligned
        result["basis_total_bps"] = ((perp_price - benchmark_aligned) / benchmark_aligned) * 10_000
        result["oracle_error_bps"] = ((oracle_price - benchmark_aligned) / benchmark_aligned) * 10_000
    else:
        result["basis_total_bps"] = np.nan
        result["oracle_error_bps"] = np.nan

    result["perp_premium_bps"] = ((perp_price - oracle_price) / oracle_price) * 10_000
    return result


def depth_profile(
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    mid: float,
    bands_bps: list[float] = [2, 3, 5, 10, 25, 50],
) -> dict:
    """Compute cumulative depth within basis-point bands from mid.

    Args:
        bids: [(price, size), ...] sorted descending
        asks: [(price, size), ...] sorted ascending
        mid: midpoint price
        bands_bps: basis point bands to measure
    """
    profile = {}
    for band in bands_bps:
        threshold = band / 10_000
        bid_depth = sum(
            p * s for p, s in bids
            if p >= mid * (1 - threshold)
        )
        ask_depth = sum(
            p * s for p, s in asks
            if p <= mid * (1 + threshold)
        )
        profile[f"bid_{band}bps"] = bid_depth
        profile[f"ask_{band}bps"] = ask_depth
        profile[f"total_{band}bps"] = bid_depth + ask_depth
        profile[f"imbalance_{band}bps"] = (
            (bid_depth - ask_depth) / (bid_depth + ask_depth)
            if (bid_depth + ask_depth) > 0 else 0
        )
    return profile


def funding_carry_pnl(
    funding_rates: pd.Series,
    position_side: str = "short",
    notional: float = 100_000,
    periods_per_day: int = 3,  # 8h funding
) -> pd.DataFrame:
    """Compute cumulative funding carry PnL for a constant-notional position.

    Shorts collect positive funding; longs collect negative funding.
    """
    sign = 1 if position_side == "short" else -1
    pnl_per_period = funding_rates * notional * sign
    cum_pnl = pnl_per_period.cumsum()
    annualized_rate = funding_rates.mean() * periods_per_day * 365.25

    return pd.DataFrame({
        "funding_rate": funding_rates,
        "period_pnl": pnl_per_period,
        "cumulative_pnl": cum_pnl,
        "annualized_rate": annualized_rate,
    })


def regime_partition(
    df: pd.DataFrame,
    regimes: dict[str, tuple[str, str]],
    time_col: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Partition a DataFrame into named time regimes.

    Args:
        regimes: {"pre_crash": ("2025-01-30 12:00", "2025-01-30 17:00"), ...}
    """
    idx = df[time_col] if time_col else df.index
    result = {}
    for name, (start, end) in regimes.items():
        mask = (idx >= pd.Timestamp(start)) & (idx < pd.Timestamp(end))
        result[name] = df[mask].copy()
    return result


def summary_statistics(series: pd.Series, name: str = "") -> dict:
    """Comprehensive distribution summary -- the table you'd put in a research paper."""
    if len(series) == 0:
        return {"name": name, "n": 0}
    return {
        "name": name,
        "n": len(series),
        "mean": float(series.mean()),
        "median": float(series.median()),
        "std": float(series.std()),
        "p5": float(series.quantile(0.05)),
        "p25": float(series.quantile(0.25)),
        "p75": float(series.quantile(0.75)),
        "p90": float(series.quantile(0.90)),
        "p95": float(series.quantile(0.95)),
        "p99": float(series.quantile(0.99)),
        "skew": float(series.skew()),
        "kurtosis": float(series.kurtosis()),
        "min": float(series.min()),
        "max": float(series.max()),
    }
