"""Tests for the backtesting engine."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import pytest

from src.engine.portfolio import Portfolio, Position
from src.engine.backtest import BacktestEngine
from src.strategies.momentum import CrossAssetMomentum
from src.strategies.mean_reversion import MeanReversion


def _make_ohlcv(n: int = 100, start_price: float = 100.0, trend: float = 0.001) -> pd.DataFrame:
    """Generate synthetic OHLCV data."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    returns = np.random.normal(trend, 0.02, n)
    prices = start_price * np.cumprod(1 + returns)
    return pd.DataFrame({
        "open": prices * (1 - 0.005 * np.random.rand(n)),
        "high": prices * (1 + 0.01 * np.random.rand(n)),
        "low": prices * (1 - 0.01 * np.random.rand(n)),
        "close": prices,
        "volume": np.random.uniform(1e6, 1e7, n),
    }, index=dates)


class TestPortfolio:
    def test_initial_state(self):
        p = Portfolio(initial_capital=50_000)
        assert p.cash == 50_000
        assert p.equity == 50_000
        assert len(p.positions) == 0

    def test_open_close_long(self):
        p = Portfolio(initial_capital=100_000, commission_bps=0, slippage_bps=0)
        pos = p.open_position("BTC", "long", 50_000, size=1.0, timestamp="t0")
        assert pos is not None
        assert p.cash == 50_000
        assert "BTC" in p.positions

        trade = p.close_position("BTC", 55_000, timestamp="t1")
        assert trade is not None
        assert trade.pnl == 5_000
        assert "BTC" not in p.positions

    def test_open_close_short(self):
        p = Portfolio(initial_capital=100_000, commission_bps=0, slippage_bps=0)
        p.open_position("ETH", "short", 3_000, size=10.0, timestamp="t0")
        trade = p.close_position("ETH", 2_800, timestamp="t1")
        assert trade is not None
        assert trade.pnl == 2_000  # 10 * (3000 - 2800)

    def test_stop_loss(self):
        p = Portfolio(initial_capital=100_000, commission_bps=0, slippage_bps=0)
        p.open_position("BTC", "long", 50_000, size=1.0, stop_loss=48_000, timestamp="t0")
        p.update({"BTC": 47_000}, timestamp="t1")
        assert "BTC" not in p.positions
        assert len(p.closed_trades) == 1

    def test_commission(self):
        p = Portfolio(initial_capital=100_000, commission_bps=10, slippage_bps=0)  # 0.1%
        p.open_position("BTC", "long", 50_000, size=1.0, timestamp="t0")
        trade = p.close_position("BTC", 50_000, timestamp="t1")
        assert trade.commission > 0
        assert trade.pnl < 0  # lost money to commissions

    def test_max_drawdown_kill(self):
        p = Portfolio(initial_capital=100_000, max_drawdown_pct=0.10, commission_bps=0, slippage_bps=0)
        p.open_position("BTC", "long", 50_000, size=1.5, timestamp="t0")
        # Price drops 15% → drawdown > 10%
        p.update({"BTC": 42_500}, timestamp="t1")
        assert p._killed
        assert len(p.positions) == 0

    def test_position_sizing_pct(self):
        p = Portfolio(initial_capital=100_000, commission_bps=0, slippage_bps=0, max_position_pct=0.20)
        pos = p.open_position("BTC", "long", 50_000, pct_of_equity=0.50, timestamp="t0")
        # Should be capped to 20%
        assert pos.notional <= 20_001  # allow small float rounding


class TestPosition:
    def test_unrealized_pnl_long(self):
        pos = Position("BTC", "long", 50_000, 2.0)
        assert pos.unrealized_pnl(55_000) == 10_000

    def test_unrealized_pnl_short(self):
        pos = Position("ETH", "short", 3_000, 10.0)
        assert pos.unrealized_pnl(2_800) == 2_000

    def test_should_stop(self):
        pos = Position("BTC", "long", 50_000, 1.0, stop_loss=48_000)
        assert pos.should_stop(47_000)
        assert not pos.should_stop(49_000)


class TestBacktestEngine:
    def test_runs_without_error(self):
        data = {"SYNTH": _make_ohlcv(200)}
        strategy = CrossAssetMomentum(fast_period=5, slow_period=20)
        engine = BacktestEngine(strategy, data, initial_capital=100_000)
        result = engine.run()
        assert result is not None
        assert not result.equity_curve.empty

    def test_mean_reversion_runs(self):
        data = {"SYNTH": _make_ohlcv(200, trend=0.0)}  # flat market
        strategy = MeanReversion(bb_period=15, rsi_period=10)
        engine = BacktestEngine(strategy, data, initial_capital=100_000)
        result = engine.run()
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
