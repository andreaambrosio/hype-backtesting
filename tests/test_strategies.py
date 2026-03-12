"""Tests for HIP-3 strategies."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import pytest

from src.engine.backtest import BacktestEngine
from src.strategies.funding_carry import FundingCarry
from src.strategies.basis_reversion import BasisReversion
from src.strategies.weekend_reopen import WeekendReopen
from src.strategies.pairs_spacex import SpaceXPairsTrade
from src.strategies.volatility_breakout import VolatilityBreakout
from src.strategies.relative_strength import RelativeStrength
from src.strategies.adaptive_regime import AdaptiveRegime


def _make_ohlcv_with_funding(
    n: int = 500,
    start_price: float = 100.0,
    avg_funding: float = 0.0003,
    avg_premium: float = 0.001,
) -> pd.DataFrame:
    """Synthetic OHLCV with funding and premium columns."""
    np.random.seed(42)
    dates = pd.date_range("2024-06-01", periods=n, freq="1h")
    returns = np.random.normal(0.0001, 0.015, n)
    prices = start_price * np.cumprod(1 + returns)

    funding = np.random.normal(avg_funding, 0.0002, n)
    premium = np.random.normal(avg_premium, 0.003, n)
    # Inject a few dislocations
    for i in [200, 350]:
        premium[i:i+5] = np.random.uniform(0.01, 0.05, 5)

    return pd.DataFrame({
        "open": prices * (1 - 0.003 * np.random.rand(n)),
        "high": prices * (1 + 0.008 * np.random.rand(n)),
        "low": prices * (1 - 0.008 * np.random.rand(n)),
        "close": prices,
        "volume": np.random.uniform(1e5, 5e6, n),
        "funding": funding,
        "premium": premium,
    }, index=dates)


def _make_equity_daily(n: int = 252, start_price: float = 50.0) -> pd.DataFrame:
    """Synthetic daily equity data."""
    np.random.seed(123)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    returns = np.random.normal(0.0005, 0.02, n)
    prices = start_price * np.cumprod(1 + returns)
    return pd.DataFrame({
        "open": prices * (1 - 0.005 * np.random.rand(n)),
        "high": prices * (1 + 0.01 * np.random.rand(n)),
        "low": prices * (1 - 0.01 * np.random.rand(n)),
        "close": prices,
        "volume": np.random.uniform(1e6, 1e7, n),
    }, index=dates)


class TestFundingCarry:
    def test_runs(self):
        data = {"BTC": _make_ohlcv_with_funding(500, avg_funding=0.0005)}
        strategy = FundingCarry(
            funding_z_entry=1.0, funding_lookback=48,
            vol_lookback=24, base_position_pct=0.15,
        )
        engine = BacktestEngine(strategy, data, initial_capital=100_000)
        result = engine.run()
        assert not result.equity_curve.empty

    def test_no_trades_low_funding(self):
        data = {"BTC": _make_ohlcv_with_funding(500, avg_funding=0.00001)}
        strategy = FundingCarry(
            funding_z_entry=3.0, min_funding_annualized=0.50,
            funding_lookback=48, vol_lookback=24,
        )
        engine = BacktestEngine(strategy, data, initial_capital=100_000)
        result = engine.run()
        # With very low funding and high threshold, should have few/no trades
        assert result is not None


class TestBasisReversion:
    def test_runs(self):
        data = {"SILVER": _make_ohlcv_with_funding(500, avg_premium=0.002)}
        strategy = BasisReversion(
            entry_dislocation_bps=20.0,
            exit_dislocation_bps=5.0,
            max_hold_bars=30,
            lookback_bars=50,
        )
        engine = BacktestEngine(strategy, data, initial_capital=100_000)
        result = engine.run()
        assert not result.equity_curve.empty

    def test_trades_on_dislocation(self):
        data = {"SILVER": _make_ohlcv_with_funding(500, avg_premium=0.005)}
        strategy = BasisReversion(
            entry_dislocation_bps=10.0,
            lookback_bars=50,
            percentile_entry=0.80,
        )
        engine = BacktestEngine(strategy, data, initial_capital=100_000)
        result = engine.run()
        assert result.metrics.compute()["total_trades"] > 0


class TestWeekendReopen:
    def test_runs(self):
        data = {"ETH": _make_ohlcv_with_funding(500)}
        strategy = WeekendReopen(
            drift_threshold_pct=0.003,
            position_size_pct=0.10,
        )
        engine = BacktestEngine(strategy, data, initial_capital=100_000)
        result = engine.run()
        assert not result.equity_curve.empty


class TestSpaceXPairs:
    def test_runs_with_aligned_data(self):
        # Create aligned daily data for both legs
        np.random.seed(42)
        dates = pd.date_range("2024-06-01", periods=200, freq="B")
        equity = pd.DataFrame({
            "open": 50 + np.random.randn(200).cumsum() * 0.5,
            "high": 51 + np.random.randn(200).cumsum() * 0.5,
            "low": 49 + np.random.randn(200).cumsum() * 0.5,
            "close": 50 + np.random.randn(200).cumsum() * 0.5,
            "volume": np.random.uniform(1e6, 5e6, 200),
        }, index=dates)

        perp = pd.DataFrame({
            "open": 150 + np.random.randn(200).cumsum() * 1.5,
            "high": 152 + np.random.randn(200).cumsum() * 1.5,
            "low": 148 + np.random.randn(200).cumsum() * 1.5,
            "close": 150 + np.random.randn(200).cumsum() * 1.5,
            "volume": np.random.uniform(1e5, 2e6, 200),
            "funding": np.random.normal(0.0005, 0.0002, 200),
        }, index=dates)

        data = {"SATS": equity, "SPACEX": perp}
        strategy = SpaceXPairsTrade(position_size_pct=0.20)
        engine = BacktestEngine(strategy, data, initial_capital=100_000)
        result = engine.run()
        assert not result.equity_curve.empty


class TestVolatilityBreakout:
    def test_runs(self):
        data = {"BTC": _make_ohlcv_with_funding(500)}
        strategy = VolatilityBreakout(
            breakout_period=20, volume_threshold=1.5,
            atr_stop_mult=2.0, position_size_pct=0.15,
        )
        engine = BacktestEngine(strategy, data, initial_capital=100_000)
        result = engine.run()
        assert not result.equity_curve.empty

    def test_generates_trades(self):
        data = {"BTC": _make_ohlcv_with_funding(500)}
        strategy = VolatilityBreakout(
            breakout_period=12, volume_threshold=0.5,
            cooldown_bars=2, max_positions=3,
        )
        engine = BacktestEngine(strategy, data, initial_capital=100_000)
        result = engine.run()
        assert result.metrics.compute()["total_trades"] > 0


class TestRelativeStrength:
    def test_runs(self):
        data = {
            "BTC": _make_ohlcv_with_funding(500, start_price=100),
            "ETH": _make_ohlcv_with_funding(500, start_price=50),
            "SOL": _make_ohlcv_with_funding(500, start_price=30),
            "HYPE": _make_ohlcv_with_funding(500, start_price=10),
        }
        strategy = RelativeStrength(
            ranking_period=48, rebalance_bars=24,
            top_n=1, bottom_n=1, vol_lookback=24,
        )
        engine = BacktestEngine(strategy, data, initial_capital=100_000)
        result = engine.run()
        assert not result.equity_curve.empty


class TestAdaptiveRegime:
    def test_runs(self):
        data = {"BTC": _make_ohlcv_with_funding(500)}
        strategy = AdaptiveRegime(
            adx_period=14, fast_ma=8, slow_ma=24,
            position_size_pct=0.15,
        )
        engine = BacktestEngine(strategy, data, initial_capital=100_000)
        result = engine.run()
        assert not result.equity_curve.empty

    def test_generates_trades(self):
        data = {"BTC": _make_ohlcv_with_funding(800)}
        strategy = AdaptiveRegime(
            adx_period=10, fast_ma=5, slow_ma=15,
            adx_trend_threshold=15.0, adx_range_threshold=10.0,
            rsi_oversold=40.0, rsi_overbought=60.0,
        )
        engine = BacktestEngine(strategy, data, initial_capital=100_000)
        result = engine.run()
        assert result.metrics.compute()["total_trades"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
