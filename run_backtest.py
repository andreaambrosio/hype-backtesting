#!/usr/bin/env python3
"""Run backtests -- examples for all strategies."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.data.hyperliquid import HyperliquidClient
from src.data.equities import EquitiesClient
from src.engine.backtest import BacktestEngine
from src.strategies.funding_arb import FundingRateArb
from src.strategies.basis_trade import BasisTrade
from src.strategies.momentum import CrossAssetMomentum
from src.strategies.mean_reversion import MeanReversion
from src.analytics.visualization import plot_backtest, plot_comparison

import matplotlib.pyplot as plt


def run_crypto_momentum():
    """Momentum strategy on BTC + ETH using Hyperliquid candles."""
    print("\n═══ CRYPTO MOMENTUM ═══\n")
    hl = HyperliquidClient()

    start_ms = int((time.time() - 180 * 86400) * 1000)  # 6 months
    data = {}
    for coin in ["BTC", "ETH", "SOL"]:
        df = hl.get_candles(coin, interval="1h", start_ms=start_ms)
        if not df.empty:
            data[coin] = df
            print(f"  {coin}: {len(df)} candles loaded")

    if not data:
        print("  No data available -- check Hyperliquid API")
        return None

    strategy = CrossAssetMomentum(fast_period=12, slow_period=36, position_size_pct=0.20)
    engine = BacktestEngine(strategy, data, initial_capital=100_000, commission_bps=2.0)
    return engine.run()


def run_funding_arb():
    """Funding rate arb on BTC + ETH."""
    print("\n═══ FUNDING RATE ARB ═══\n")
    hl = HyperliquidClient()

    start_ms = int((time.time() - 90 * 86400) * 1000)  # 3 months

    # We need candles with funding data merged
    data = {}
    for coin in ["BTC", "ETH"]:
        candles = hl.get_candles(coin, interval="1h", start_ms=start_ms)
        funding = hl.get_funding_history(coin, start_ms=start_ms)

        if candles.empty:
            continue

        # Merge funding into candle data (forward-fill since funding is 8h)
        if not funding.empty:
            candles = candles.join(funding[["fundingRate", "premium"]], how="left")
            candles["fundingRate"] = candles["fundingRate"].ffill().fillna(0)
            candles["premium"] = candles["premium"].ffill().fillna(0)
            candles = candles.rename(columns={"fundingRate": "funding"})
        else:
            candles["funding"] = 0.0
            candles["premium"] = 0.0

        data[coin] = candles
        print(f"  {coin}: {len(candles)} bars with funding data")

    if not data:
        print("  No data available")
        return None

    strategy = FundingRateArb(entry_threshold=0.0003, position_size_pct=0.15)
    engine = BacktestEngine(strategy, data, initial_capital=100_000, commission_bps=2.0)
    return engine.run()


def run_equities_mean_reversion():
    """Mean reversion on US tech stocks."""
    print("\n═══ EQUITIES MEAN REVERSION ═══\n")
    eq = EquitiesClient()

    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
    data = {}
    for t in tickers:
        df = eq.get_ohlcv(t, interval="1d", period="2y")
        if not df.empty:
            data[t] = df
            print(f"  {t}: {len(df)} daily bars")

    if not data:
        print("  No data available")
        return None

    strategy = MeanReversion(bb_period=20, rsi_period=14, position_size_pct=0.12)
    engine = BacktestEngine(strategy, data, initial_capital=100_000, commission_bps=1.0, slippage_bps=2.0)
    return engine.run()


def run_equities_momentum():
    """Momentum on sector ETFs."""
    print("\n═══ SECTOR MOMENTUM ═══\n")
    eq = EquitiesClient()

    tickers = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLB", "XLU", "XLRE"]
    data = {}
    for t in tickers:
        df = eq.get_ohlcv(t, interval="1d", period="2y")
        if not df.empty:
            data[t] = df
            print(f"  {t}: {len(df)} daily bars")

    if not data:
        print("  No data available")
        return None

    strategy = CrossAssetMomentum(fast_period=10, slow_period=50, trailing_stop_pct=0.04)
    engine = BacktestEngine(strategy, data, initial_capital=100_000, commission_bps=0.5, slippage_bps=1.0)
    return engine.run()


if __name__ == "__main__":
    results = []

    # Run all strategies
    r1 = run_crypto_momentum()
    if r1:
        results.append({"name": r1.strategy_name, "equity_df": r1.equity_curve, "metrics": r1.metrics.compute()})
        fig = plot_backtest(r1.equity_curve, r1.trades, title=f"Backtest: {r1.strategy_name}")
        fig.savefig("output/crypto_momentum.png", dpi=150, bbox_inches="tight", facecolor="#0a0a0a")
        plt.close()

    r2 = run_funding_arb()
    if r2:
        results.append({"name": r2.strategy_name, "equity_df": r2.equity_curve, "metrics": r2.metrics.compute()})
        fig = plot_backtest(r2.equity_curve, r2.trades, title=f"Backtest: {r2.strategy_name}")
        fig.savefig("output/funding_arb.png", dpi=150, bbox_inches="tight", facecolor="#0a0a0a")
        plt.close()

    r3 = run_equities_mean_reversion()
    if r3:
        results.append({"name": r3.strategy_name, "equity_df": r3.equity_curve, "metrics": r3.metrics.compute()})
        fig = plot_backtest(r3.equity_curve, r3.trades, title=f"Backtest: {r3.strategy_name}")
        fig.savefig("output/equities_mean_reversion.png", dpi=150, bbox_inches="tight", facecolor="#0a0a0a")
        plt.close()

    r4 = run_equities_momentum()
    if r4:
        results.append({"name": r4.strategy_name, "equity_df": r4.equity_curve, "metrics": r4.metrics.compute()})
        fig = plot_backtest(r4.equity_curve, r4.trades, title=f"Backtest: {r4.strategy_name}")
        fig.savefig("output/sector_momentum.png", dpi=150, bbox_inches="tight", facecolor="#0a0a0a")
        plt.close()

    # Comparison chart
    if len(results) >= 2:
        fig = plot_comparison(results, title="Strategy Comparison -- All Backtests")
        fig.savefig("output/comparison.png", dpi=150, bbox_inches="tight", facecolor="#0a0a0a")
        plt.close()

    print("\n✓ All charts saved to output/")
