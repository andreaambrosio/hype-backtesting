#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════════════════════════
HIP-3 MICROSTRUCTURE & STRATEGY ANALYSIS
════════════════════════════════════════════════════════════════════════════════

Pulls live data from Hyperliquid and yfinance, runs all strategies,
and generates performance tables + charts.

Strategies:
    1. Funding Rate Carry
    2. Basis Dislocation Reversion
    3. Weekend-to-Reopen Positioning
    4. SpaceX L/S Pairs
    5. Volatility Breakout
    6. Cross-Asset Relative Strength
    7. Adaptive Regime

Output: performance tables, equity curves, microstructure stats, comparison charts.
"""

import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.hyperliquid import HyperliquidClient
from src.data.equities import EquitiesClient
from src.engine.backtest import BacktestEngine
from src.strategies.funding_carry import FundingCarry
from src.strategies.basis_reversion import BasisReversion
from src.strategies.weekend_reopen import WeekendReopen
from src.strategies.pairs_spacex import SpaceXPairsTrade
from src.strategies.momentum import CrossAssetMomentum
from src.strategies.mean_reversion import MeanReversion
from src.strategies.volatility_breakout import VolatilityBreakout
from src.strategies.relative_strength import RelativeStrength
from src.strategies.adaptive_regime import AdaptiveRegime
from src.research.microstructure import (
    summary_statistics,
    funding_carry_pnl,
    realized_volatility,
    roll_spread,
    amihud_illiquidity,
)
from src.analytics.visualization import plot_backtest, plot_comparison

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

console = Console()
OUTPUT = Path("output")
OUTPUT.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# DATA ACQUISITION
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_hyperliquid_data(
    coins: list[str],
    days: int = 90,
    interval: str = "1h",
) -> dict[str, pd.DataFrame]:
    """Fetch candles + funding for multiple HL coins."""
    hl = HyperliquidClient(cache_ttl_hours=12)
    start_ms = int((time.time() - days * 86400) * 1000)
    data = {}

    for coin in coins:
        console.print(f"  Fetching [cyan]{coin}[/] candles ({interval}, {days}d)...")
        candles = hl.get_candles(coin, interval=interval, start_ms=start_ms)

        if candles.empty:
            console.print(f"    [yellow]No candle data for {coin}[/]")
            continue

        # Fetch funding history and merge
        console.print(f"  Fetching [cyan]{coin}[/] funding history...")
        try:
            funding = hl.get_funding_history(coin, start_ms=start_ms)
            if not funding.empty:
                candles = candles.join(funding[["fundingRate", "premium"]], how="left")
                candles["fundingRate"] = candles["fundingRate"].ffill().fillna(0)
                candles["premium"] = candles["premium"].ffill().fillna(0)
                candles = candles.rename(columns={"fundingRate": "funding"})
            else:
                candles["funding"] = 0.0
                candles["premium"] = 0.0
        except Exception as e:
            console.print(f"    [yellow]Funding fetch failed: {e}[/]")
            candles["funding"] = 0.0
            candles["premium"] = 0.0

        data[coin] = candles
        console.print(f"    [green]{len(candles)} bars loaded[/]")

    return data


def fetch_equity_data(
    tickers: list[str],
    period: str = "1y",
    interval: str = "1d",
) -> dict[str, pd.DataFrame]:
    """Fetch equity OHLCV data."""
    eq = EquitiesClient(cache_ttl_hours=12)
    data = {}
    for t in tickers:
        console.print(f"  Fetching [cyan]{t}[/] ({interval}, {period})...")
        df = eq.get_ohlcv(t, interval=interval, period=period)
        if not df.empty:
            data[t] = df
            console.print(f"    [green]{len(df)} bars loaded[/]")
        else:
            console.print(f"    [yellow]No data for {t}[/]")
    return data


# ═══════════════════════════════════════════════════════════════════════════════
# MICROSTRUCTURE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_microstructure(data: dict[str, pd.DataFrame]):
    """Compute microstructure metrics for each asset."""
    console.print(Panel("[bold]MICROSTRUCTURE ANALYSIS[/]", style="cyan"))

    for coin, df in data.items():
        if df.empty:
            continue

        returns = df["close"].pct_change().dropna()

        # Realized vol
        rvol = realized_volatility(returns, annualize=365.25 * 24)

        # Roll implied spread
        roll = roll_spread(returns)

        # Amihud illiquidity
        if "volume" in df.columns:
            vol_usd = df["volume"] * df["close"]
            amihud = amihud_illiquidity(returns, vol_usd.iloc[1:])
        else:
            amihud = np.nan

        # Funding analysis
        if "funding" in df.columns:
            funding = df["funding"]
            f_stats = summary_statistics(funding * 10_000, f"{coin} Funding (bps)")
            f_annual = float(funding.mean()) * 3 * 365.25  # 3 periods/day, annualized
        else:
            f_stats = {}
            f_annual = 0.0

        # Premium analysis
        if "premium" in df.columns:
            premium = df["premium"]
            p_stats = summary_statistics(premium * 10_000, f"{coin} Premium (bps)")
        else:
            p_stats = {}

        # Print table
        table = Table(
            title=f"{coin} -- Microstructure Summary",
            box=box.DOUBLE_EDGE,
            show_lines=True,
        )
        table.add_column("Metric", style="cyan", width=30)
        table.add_column("Value", style="bold white", justify="right", width=20)

        table.add_row("Bars", f"{len(df):,}")
        table.add_row("Date Range", f"{df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}")
        table.add_row("Close (last)", f"${float(df['close'].iloc[-1]):,.2f}")
        table.add_row("Annualized Vol", f"{rvol:.1%}")
        table.add_row("Roll Implied Spread", f"{roll * 10_000:.2f} bps")
        table.add_row("Amihud Illiquidity", f"{amihud:.2e}" if not np.isnan(amihud) else "N/A")

        if f_stats:
            table.add_row("─── Funding ───", "")
            table.add_row("Annualized Rate", f"{f_annual:.1%}")
            table.add_row("Median (bps/period)", f"{f_stats.get('median', 0):.4f}")
            table.add_row("Std (bps/period)", f"{f_stats.get('std', 0):.4f}")
            table.add_row("P5 / P95 (bps)", f"{f_stats.get('p5', 0):.4f} / {f_stats.get('p95', 0):.4f}")

        if p_stats:
            table.add_row("─── Premium ───", "")
            table.add_row("Median (bps)", f"{p_stats.get('median', 0):.2f}")
            table.add_row("P5 / P95 (bps)", f"{p_stats.get('p5', 0):.2f} / {p_stats.get('p95', 0):.2f}")
            table.add_row("Max |Premium| (bps)", f"{max(abs(p_stats.get('min', 0)), abs(p_stats.get('max', 0))):.2f}")

        console.print(table)
        console.print()


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY BACKTESTS
# ═══════════════════════════════════════════════════════════════════════════════

def run_strategy_1_funding_carry(crypto_data: dict[str, pd.DataFrame]) -> dict | None:
    """Strategy 1: Funding Rate Carry on HIP-3 TradFi perps."""
    console.print(Panel("[bold]STRATEGY 1: FUNDING RATE CARRY[/]", style="green"))
    console.print("Thesis: Collect elevated funding on TradFi perps (41%+ annualized on SpaceX).")
    console.print("Edge: Vol-adjusted sizing prevents blowup during dislocations.\n")

    coins_with_funding = {k: v for k, v in crypto_data.items() if "funding" in v.columns}
    if not coins_with_funding:
        console.print("[yellow]No funding data available -- skipping[/]")
        return None

    strategy = FundingCarry(
        funding_z_entry=1.0,           # lower z to match real HL data
        funding_z_exit=0.2,
        vol_lookback=72,
        funding_lookback=72,            # 3 days lookback (hourly)
        max_annualized_vol=3.00,        # allow high-vol altcoins (TURBO etc)
        base_position_pct=0.15,
        vol_scalar=True,
        target_vol=0.20,
        max_drawdown_per_trade=0.08,
        min_funding_annualized=0.05,    # 5% min -- captures BTC/ETH when elevated
    )

    engine = BacktestEngine(
        strategy, coins_with_funding,
        initial_capital=100_000, commission_bps=2.0, slippage_bps=1.0,
    )
    result = engine.run()

    fig = plot_backtest(result.equity_curve, result.trades, title="Strategy 1: Funding Rate Carry")
    fig.savefig(OUTPUT / "s1_funding_carry.png", dpi=200, bbox_inches="tight", facecolor="#0a0a0a")
    plt.close()

    return {"name": result.strategy_name, "equity_df": result.equity_curve,
            "metrics": result.metrics.compute(), "result": result}


def run_strategy_2_basis_reversion(crypto_data: dict[str, pd.DataFrame]) -> dict | None:
    """Strategy 2: Basis Dislocation Reversion."""
    console.print(Panel("[bold]STRATEGY 2: BASIS DISLOCATION REVERSION[/]", style="green"))
    console.print("Thesis: Mark-oracle basis peaks are short-lived (95s >400bps on silver).")
    console.print("Edge: Fade extreme dislocations with time-based exit.\n")

    coins_with_premium = {k: v for k, v in crypto_data.items() if "premium" in v.columns}
    if not coins_with_premium:
        console.print("[yellow]No premium data available -- skipping[/]")
        return None

    strategy = BasisReversion(
        entry_dislocation_bps=3.0,      # real HL BTC premium is ~3-5 bps
        exit_dislocation_bps=1.0,
        max_hold_bars=24,
        lookback_bars=72,
        percentile_entry=0.90,
        base_position_pct=0.12,
        dislocation_scalar=True,
        max_position_pct=0.25,
        stop_loss_bps=50.0,
    )

    engine = BacktestEngine(
        strategy, coins_with_premium,
        initial_capital=100_000, commission_bps=2.0, slippage_bps=1.0,
    )
    result = engine.run()

    fig = plot_backtest(result.equity_curve, result.trades, title="Strategy 2: Basis Dislocation Reversion")
    fig.savefig(OUTPUT / "s2_basis_reversion.png", dpi=200, bbox_inches="tight", facecolor="#0a0a0a")
    plt.close()

    return {"name": result.strategy_name, "equity_df": result.equity_curve,
            "metrics": result.metrics.compute(), "result": result}


def run_strategy_3_weekend_reopen(crypto_data: dict[str, pd.DataFrame]) -> dict | None:
    """Strategy 3: Weekend-to-Reopen Positioning."""
    console.print(Panel("[bold]STRATEGY 3: WEEKEND-TO-REOPEN POSITIONING[/]", style="green"))
    console.print("Thesis: Weekend prices overshoot on thin liquidity; reopen pulls toward fundamentals.")
    console.print("Edge: Continuous HL pricing pre-auction creates a tradable gap.\n")

    if not crypto_data:
        return None

    strategy = WeekendReopen(
        drift_threshold_pct=0.002,      # 0.2% drift threshold -- lower for crypto
        reversion_pct=0.60,
        position_size_pct=0.10,
        stop_loss_pct=0.03,
        mode="mean_reversion",
    )

    engine = BacktestEngine(
        strategy, crypto_data,
        initial_capital=100_000, commission_bps=2.0, slippage_bps=1.0,
    )
    result = engine.run()

    fig = plot_backtest(result.equity_curve, result.trades, title="Strategy 3: Weekend-to-Reopen")
    fig.savefig(OUTPUT / "s3_weekend_reopen.png", dpi=200, bbox_inches="tight", facecolor="#0a0a0a")
    plt.close()

    return {"name": result.strategy_name, "equity_df": result.equity_curve,
            "metrics": result.metrics.compute(), "result": result}


def run_strategy_4_spacex_pairs(
    crypto_data: dict[str, pd.DataFrame],
    equity_data: dict[str, pd.DataFrame],
) -> dict | None:
    """Strategy 4: SpaceX L/S Pairs Trade."""
    console.print(Panel("[bold]STRATEGY 4: SPACEX L/S PAIRS (SATS / SPACEX)[/]", style="green"))
    console.print("Thesis: SATS implies $387B SpaceX valuation; HL perp trades at $1.26T.")
    console.print("Edge: Long cheap proxy + short expensive perp + collect 41% funding.\n")

    # We need SATS equity data and a SpaceX-like perp proxy
    # If we don't have SpaceX on HL, use any available crypto data as the short leg
    long_sym = None
    short_sym = None

    if "SATS" in equity_data:
        long_sym = "SATS"
    elif equity_data:
        long_sym = list(equity_data.keys())[0]

    # Try SpaceX, then fall back to highest-funding crypto
    for candidate in ["SPACEX", "SPX"]:
        if candidate in crypto_data:
            short_sym = candidate
            break
    if short_sym is None and crypto_data:
        # Use the asset with highest average funding as proxy
        best_funding = 0
        for sym, df in crypto_data.items():
            if "funding" in df.columns:
                avg_f = abs(float(df["funding"].mean()))
                if avg_f > best_funding:
                    best_funding = avg_f
                    short_sym = sym

    if not long_sym or not short_sym:
        console.print("[yellow]Insufficient data for pairs trade -- need equity + crypto[/]")
        return None

    console.print(f"  Long leg: [green]{long_sym}[/] (equity)")
    console.print(f"  Short leg: [red]{short_sym}[/] (perp)")

    # Combine data -- resample crypto to daily to align with equities
    combined = {}
    if long_sym in equity_data:
        eq_df = equity_data[long_sym].copy()
        eq_df.index = eq_df.index.tz_localize(None) if eq_df.index.tz else eq_df.index
        combined[long_sym] = eq_df

    if short_sym in crypto_data:
        crypto_df = crypto_data[short_sym].copy()
        # Resample hourly crypto to daily OHLCV
        daily = crypto_df.resample("1D").agg({
            "open": "first", "high": "max", "low": "min", "close": "last",
            "volume": "sum",
        }).dropna()
        if "funding" in crypto_df.columns:
            daily["funding"] = crypto_df["funding"].resample("1D").mean()
        daily.index = daily.index.tz_localize(None) if hasattr(daily.index, 'tz') and daily.index.tz else daily.index
        combined[short_sym] = daily

    if len(combined) < 2:
        console.print("[yellow]Could not align both legs[/]")
        return None

    # Determine funding rate from data
    short_df = crypto_data[short_sym]
    if "funding" in short_df.columns:
        avg_funding_annual = float(short_df["funding"].mean()) * 3 * 365.25
    else:
        avg_funding_annual = 0.15

    strategy = SpaceXPairsTrade(
        hedge_ratio=1.0,
        rebalance_threshold=0.10,
        rebalance_days=7,
        short_leverage=1.3,
        collect_funding=True,
        funding_rate_annual=abs(avg_funding_annual),
        position_size_pct=0.25,
    )

    engine = BacktestEngine(
        strategy, combined,
        initial_capital=100_000, commission_bps=2.0, slippage_bps=2.0,
    )
    result = engine.run()

    fig = plot_backtest(result.equity_curve, result.trades,
                        title=f"Strategy 4: L/S Pairs ({long_sym} / {short_sym})")
    fig.savefig(OUTPUT / "s4_spacex_pairs.png", dpi=200, bbox_inches="tight", facecolor="#0a0a0a")
    plt.close()

    return {"name": result.strategy_name, "equity_df": result.equity_curve,
            "metrics": result.metrics.compute(), "result": result}


def run_strategy_5_volatility_breakout(crypto_data: dict[str, pd.DataFrame]) -> dict | None:
    """Strategy 5: Volatility Breakout on HL perps."""
    console.print(Panel("[bold]STRATEGY 5: VOLATILITY BREAKOUT[/]", style="green"))
    console.print("Thesis: Range expansions with volume confirmation signal continuation.")
    console.print("Edge: ATR-based trailing stops lock in gains on breakout moves.\n")

    if not crypto_data:
        return None

    strategy = VolatilityBreakout(
        breakout_period=24,
        volume_threshold=1.5,
        atr_period=14,
        atr_stop_mult=2.0,
        position_size_pct=0.15,
        cooldown_bars=4,
        max_positions=3,
    )

    engine = BacktestEngine(
        strategy, crypto_data,
        initial_capital=100_000, commission_bps=2.0, slippage_bps=1.0,
    )
    result = engine.run()

    fig = plot_backtest(result.equity_curve, result.trades, title="Strategy 5: Volatility Breakout")
    fig.savefig(OUTPUT / "s5_volatility_breakout.png", dpi=200, bbox_inches="tight", facecolor="#0a0a0a")
    plt.close()

    return {"name": result.strategy_name, "equity_df": result.equity_curve,
            "metrics": result.metrics.compute(), "result": result}


def run_strategy_6_relative_strength(crypto_data: dict[str, pd.DataFrame]) -> dict | None:
    """Strategy 6: Cross-Asset Relative Strength L/S."""
    console.print(Panel("[bold]STRATEGY 6: CROSS-ASSET RELATIVE STRENGTH[/]", style="green"))
    console.print("Thesis: Cross-sectional momentum -- long strongest, short weakest.")
    console.print("Edge: Risk-parity weighting normalizes vol across legs.\n")

    if len(crypto_data) < 4:
        console.print("[yellow]Need ≥4 assets for relative strength -- skipping[/]")
        return None

    strategy = RelativeStrength(
        ranking_period=72,
        rebalance_bars=24,
        top_n=2,
        bottom_n=2,
        vol_lookback=48,
        position_size_pct=0.12,
        risk_parity=True,
    )

    engine = BacktestEngine(
        strategy, crypto_data,
        initial_capital=100_000, commission_bps=2.0, slippage_bps=1.0,
    )
    result = engine.run()

    fig = plot_backtest(result.equity_curve, result.trades, title="Strategy 6: Relative Strength L/S")
    fig.savefig(OUTPUT / "s6_relative_strength.png", dpi=200, bbox_inches="tight", facecolor="#0a0a0a")
    plt.close()

    return {"name": result.strategy_name, "equity_df": result.equity_curve,
            "metrics": result.metrics.compute(), "result": result}


def run_strategy_7_adaptive_regime(crypto_data: dict[str, pd.DataFrame]) -> dict | None:
    """Strategy 7: Adaptive Regime -- switch between momentum and mean-reversion."""
    console.print(Panel("[bold]STRATEGY 7: ADAPTIVE REGIME[/]", style="green"))
    console.print("Thesis: ADX regime detection selects optimal strategy per market state.")
    console.print("Edge: Avoids whipsaws by matching strategy to regime.\n")

    if not crypto_data:
        return None

    strategy = AdaptiveRegime(
        adx_period=14,
        adx_trend_threshold=25.0,
        adx_range_threshold=20.0,
        fast_ma=8,
        slow_ma=24,
        bb_period=20,
        bb_std=2.0,
        rsi_period=14,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        position_size_pct=0.15,
        vol_regime_size=0.08,
        atr_expansion=1.5,
        trailing_stop_atr=2.0,
    )

    engine = BacktestEngine(
        strategy, crypto_data,
        initial_capital=100_000, commission_bps=2.0, slippage_bps=1.0,
    )
    result = engine.run()

    fig = plot_backtest(result.equity_curve, result.trades, title="Strategy 7: Adaptive Regime")
    fig.savefig(OUTPUT / "s7_adaptive_regime.png", dpi=200, bbox_inches="tight", facecolor="#0a0a0a")
    plt.close()

    return {"name": result.strategy_name, "equity_df": result.equity_curve,
            "metrics": result.metrics.compute(), "result": result}


def run_benchmark_strategies(
    crypto_data: dict[str, pd.DataFrame],
    equity_data: dict[str, pd.DataFrame],
) -> list[dict]:
    """Run benchmark strategies for comparison."""
    benchmarks = []

    # Crypto momentum benchmark
    if crypto_data:
        console.print(Panel("[bold]BENCHMARK: Cross-Asset Momentum[/]", style="dim"))
        strategy = CrossAssetMomentum(fast_period=12, slow_period=36, position_size_pct=0.15)
        engine = BacktestEngine(strategy, crypto_data, initial_capital=100_000, commission_bps=2.0)
        result = engine.run()
        fig = plot_backtest(result.equity_curve, result.trades, title="Benchmark: Crypto Momentum")
        fig.savefig(OUTPUT / "bench_crypto_momentum.png", dpi=200, bbox_inches="tight", facecolor="#0a0a0a")
        plt.close()
        benchmarks.append({
            "name": "Crypto Momentum (benchmark)",
            "equity_df": result.equity_curve,
            "metrics": result.metrics.compute(),
        })

    # Equity mean reversion benchmark
    if equity_data:
        console.print(Panel("[bold]BENCHMARK: Equity Mean Reversion[/]", style="dim"))
        strategy = MeanReversion(bb_period=20, rsi_period=14, position_size_pct=0.12)
        engine = BacktestEngine(strategy, equity_data, initial_capital=100_000, commission_bps=1.0)
        result = engine.run()
        fig = plot_backtest(result.equity_curve, result.trades, title="Benchmark: Equity Mean Reversion")
        fig.savefig(OUTPUT / "bench_equity_mr.png", dpi=200, bbox_inches="tight", facecolor="#0a0a0a")
        plt.close()
        benchmarks.append({
            "name": "Equity Mean Reversion (benchmark)",
            "equity_df": result.equity_curve,
            "metrics": result.metrics.compute(),
        })

    return benchmarks


# ═══════════════════════════════════════════════════════════════════════════════
# RESULTS PRESENTATION
# ═══════════════════════════════════════════════════════════════════════════════

def print_comparison_table(all_results: list[dict]):
    """Print a single comparison table -- the money shot."""
    table = Table(
        title="STRATEGY COMPARISON -- ALL BACKTESTS",
        box=box.DOUBLE_EDGE,
        show_lines=True,
        title_style="bold white on dark_green",
    )

    table.add_column("Strategy", style="cyan", width=35)
    table.add_column("Return", justify="right", width=10)
    table.add_column("CAGR", justify="right", width=10)
    table.add_column("Sharpe", justify="right", width=8)
    table.add_column("Sortino", justify="right", width=8)
    table.add_column("Calmar", justify="right", width=8)
    table.add_column("Max DD", justify="right", width=8)
    table.add_column("Win %", justify="right", width=8)
    table.add_column("PF", justify="right", width=8)
    table.add_column("Trades", justify="right", width=8)
    table.add_column("Final $", justify="right", width=12)

    for r in all_results:
        m = r["metrics"]
        style = "bold green" if m.get("total_return", 0) > 0 else "bold red"
        table.add_row(
            r["name"],
            f"{m.get('total_return', 0):+.1%}",
            f"{m.get('cagr', 0):+.1%}",
            f"{m.get('sharpe_ratio', 0):.2f}",
            f"{m.get('sortino_ratio', 0):.2f}",
            f"{m.get('calmar_ratio', 0):.2f}",
            f"{m.get('max_drawdown', 0):.1%}",
            f"{m.get('win_rate', 0):.0%}",
            f"{m.get('profit_factor', 0):.2f}",
            f"{m.get('total_trades', 0)}",
            f"${m.get('final_equity', 100000):,.0f}",
            style=style,
        )

    console.print()
    console.print(table)
    console.print()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    console.print(Panel(
        "[bold white]HIP-3 MICROSTRUCTURE & STRATEGY ANALYSIS[/]\n"
        "Hyperliquid TradFi Perpetuals -- Institutional Research Framework\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
        style="bold cyan",
        box=box.DOUBLE_EDGE,
    ))

    # ── Data acquisition ────────────────────────────────────────────────

    console.print("\n[bold]1. DATA ACQUISITION[/]\n")

    # Hyperliquid: core crypto + high-funding coins for carry strategies
    # TURBO ~994%, MEME ~81%, WIF ~19% annualized funding
    hl_coins = ["BTC", "ETH", "SOL", "HYPE", "TURBO", "MEME", "WIF"]
    console.print("[cyan]Fetching Hyperliquid data...[/]")
    crypto_data = fetch_hyperliquid_data(hl_coins, days=90, interval="1h")

    # Equities
    eq_tickers = ["SATS", "AAPL", "NVDA", "GOOGL", "SPY"]
    console.print("\n[cyan]Fetching equity data...[/]")
    equity_data = fetch_equity_data(eq_tickers, period="1y", interval="1d")

    # HIP-3 vault analysis
    console.print("\n[cyan]Fetching HIP-3 vault summaries...[/]")
    try:
        hl = HyperliquidClient()
        vaults = hl.get_vault_summaries()
        if not vaults.empty:
            top_vaults = vaults.nlargest(10, "tvl")
            table = Table(title="Top 10 HIP-3 Vaults by TVL", box=box.SIMPLE)
            table.add_column("Name", style="cyan", width=30)
            table.add_column("TVL", justify="right", width=15)
            table.add_column("APR", justify="right", width=10)
            table.add_column("All-Time PnL", justify="right", width=15)
            table.add_column("Depositors", justify="right", width=12)
            for _, v in top_vaults.iterrows():
                table.add_row(
                    str(v["name"])[:30],
                    f"${v['tvl']:,.0f}",
                    f"{v['apr']:.1%}" if v['apr'] < 10 else f"{v['apr']:.0f}%",
                    f"${v['pnl']:,.0f}",
                    f"{v['depositors']:,}",
                )
            console.print(table)
    except Exception as e:
        console.print(f"[yellow]Vault fetch failed: {e}[/]")

    # ── Microstructure analysis ─────────────────────────────────────────

    console.print("\n[bold]2. MICROSTRUCTURE ANALYSIS[/]\n")
    analyze_microstructure(crypto_data)

    # ── Strategy backtests ──────────────────────────────────────────────

    console.print("\n[bold]3. STRATEGY BACKTESTS[/]\n")

    all_results = []

    r1 = run_strategy_1_funding_carry(crypto_data)
    if r1:
        all_results.append(r1)

    r2 = run_strategy_2_basis_reversion(crypto_data)
    if r2:
        all_results.append(r2)

    r3 = run_strategy_3_weekend_reopen(crypto_data)
    if r3:
        all_results.append(r3)

    r4 = run_strategy_4_spacex_pairs(crypto_data, equity_data)
    if r4:
        all_results.append(r4)

    r5 = run_strategy_5_volatility_breakout(crypto_data)
    if r5:
        all_results.append(r5)

    r6 = run_strategy_6_relative_strength(crypto_data)
    if r6:
        all_results.append(r6)

    r7 = run_strategy_7_adaptive_regime(crypto_data)
    if r7:
        all_results.append(r7)

    # Benchmarks
    console.print("\n[bold]4. BENCHMARK STRATEGIES[/]\n")
    benchmarks = run_benchmark_strategies(crypto_data, equity_data)
    all_results.extend(benchmarks)

    # ── Comparison ──────────────────────────────────────────────────────

    console.print("\n[bold]5. RESULTS[/]")
    print_comparison_table(all_results)

    # Comparison chart
    if len(all_results) >= 2:
        chart_results = [r for r in all_results if not r["equity_df"].empty]
        if len(chart_results) >= 2:
            fig = plot_comparison(chart_results, title="HIP-3 Strategy Comparison -- All Backtests")
            fig.savefig(OUTPUT / "hip3_comparison.png", dpi=200, bbox_inches="tight", facecolor="#0a0a0a")
            plt.close()
            console.print(f"[green]Comparison chart saved to {OUTPUT / 'hip3_comparison.png'}[/]")

    console.print(f"\n[bold green]All charts saved to {OUTPUT}/[/]")
    console.print(Panel(
        "[bold]Output Files:[/]\n"
        "  s1_funding_carry.png\n"
        "  s2_basis_reversion.png\n"
        "  s3_weekend_reopen.png\n"
        "  s4_spacex_pairs.png\n"
        "  s5_volatility_breakout.png\n"
        "  s6_relative_strength.png\n"
        "  s7_adaptive_regime.png\n"
        "  bench_crypto_momentum.png\n"
        "  bench_equity_mr.png\n"
        "  hip3_comparison.png",
        style="dim",
    ))


if __name__ == "__main__":
    main()
