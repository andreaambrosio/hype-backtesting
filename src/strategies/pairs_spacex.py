"""SpaceX Pairs Trade -- Long SATS (EchoStar) / Short SpaceX perp on Hyperliquid.

What it does:
    Pairs the cheaper equity proxy (SATS, implying ~$387B SpaceX valuation)
    against the more expensive perp (SpaceX at $1.26T on Hyperliquid).
    From HIP-3 research (@shaundadevens):
    - Funding rate: 41% annualized (paid to shorts)
    - Implied forward valuation at Jun-26 IPO: $1.45T
    - If IPO delayed to Dec-26: $1.8T implied

    The trade: long the cheap proxy (SATS) + short the expensive perp (SPACEX).
    Carry: shorts collect ~41% annualized funding.
    Convergence: at IPO, the gap between proxy and perp must close.

How it works:
    This is a relative-value / event-driven pairs trade. The backtest
    simulates it with configurable:
    - Hedge ratio (notional or beta-adjusted)
    - Rebalancing frequency
    - Funding collection
    - Convergence scenarios
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import numpy as np

from .base import Strategy
from ..engine.portfolio import Portfolio


class SpaceXPairsTrade(Strategy):
    name = "SpaceX L/S Pairs (SATS / SPACEX)"

    def __init__(
        self,
        hedge_ratio: float = 1.0,           # 1:1 notional
        rebalance_threshold: float = 0.10,    # rebalance when ratio drifts >10%
        rebalance_days: int = 7,
        short_leverage: float = 1.3,          # 1.3x on the short leg
        collect_funding: bool = True,
        funding_rate_annual: float = 0.41,    # 41% annualized (for simulation)
        max_spread_entry: float = 2.5,        # enter when SpaceX/SATS ratio > 2.5x
        stop_spread: float = 4.0,             # stop if ratio blows out to 4x
        position_size_pct: float = 0.25,
    ):
        self.hedge_ratio = hedge_ratio
        self.rebalance_threshold = rebalance_threshold
        self.rebalance_days = rebalance_days
        self.short_leverage = short_leverage
        self.collect_funding = collect_funding
        self.funding_rate_annual = funding_rate_annual
        self.max_spread_entry = max_spread_entry
        self.stop_spread = stop_spread
        self.position_size_pct = position_size_pct
        self._last_rebalance: Any = None
        self._long_sym: str = ""
        self._short_sym: str = ""
        self._spread_history: list[float] = []

    def initialize(self, symbols: list[str], portfolio: Portfolio):
        super().initialize(symbols, portfolio)
        # Convention: first symbol is long leg (equity), second is short leg (perp)
        if len(symbols) >= 2:
            self._long_sym = symbols[0]
            self._short_sym = symbols[1]

    def _current_spread(self, bar: dict) -> float | None:
        """Ratio of short leg to long leg price (normalized)."""
        if self._long_sym not in bar or self._short_sym not in bar:
            return None
        long_px = float(bar[self._long_sym].get("close", bar[self._long_sym].iloc[0]))
        short_px = float(bar[self._short_sym].get("close", bar[self._short_sym].iloc[0]))
        if long_px == 0:
            return None
        return short_px / long_px

    def on_bar(
        self,
        timestamp: Any,
        bar: dict[str, pd.Series],
        lookback: dict[str, pd.DataFrame],
        portfolio: Portfolio,
    ):
        if not self._long_sym or not self._short_sym:
            return

        spread = self._current_spread(bar)
        if spread is None:
            return

        self._spread_history.append(spread)

        long_px = float(bar[self._long_sym].get("close", bar[self._long_sym].iloc[0]))
        short_px = float(bar[self._short_sym].get("close", bar[self._short_sym].iloc[0]))

        has_long = self._long_sym in portfolio.positions
        has_short = self._short_sym in portfolio.positions

        if has_long and has_short:
            # Check stop: spread blew out
            if spread > self.stop_spread:
                portfolio.close_position(self._long_sym, long_px, timestamp)
                portfolio.close_position(self._short_sym, short_px, timestamp)
                return

            # Check rebalance
            if self._last_rebalance is not None:
                days_since = (pd.Timestamp(timestamp) - pd.Timestamp(self._last_rebalance)).days
                if days_since >= self.rebalance_days:
                    long_pos = portfolio.positions[self._long_sym]
                    short_pos = portfolio.positions[self._short_sym]
                    long_notional = long_pos.size * long_px
                    short_notional = short_pos.size * short_px
                    ratio_drift = abs(long_notional - short_notional * self.hedge_ratio) / long_notional
                    if ratio_drift > self.rebalance_threshold:
                        # Close and re-enter at correct ratio
                        portfolio.close_position(self._long_sym, long_px, timestamp)
                        portfolio.close_position(self._short_sym, short_px, timestamp)
                        has_long = has_short = False
                    else:
                        self._last_rebalance = timestamp

            # Simulate funding collection (add to cash)
            if self.collect_funding and has_short:
                short_pos = portfolio.positions.get(self._short_sym)
                if short_pos:
                    # Hourly funding = annual_rate / (365.25 * 24)
                    hourly_funding = self.funding_rate_annual / (365.25 * 24)
                    funding_pnl = short_pos.notional * hourly_funding
                    portfolio.cash += funding_pnl

        if not has_long and not has_short:
            # Entry: spread must be elevated
            if len(self._spread_history) < 20:
                return

            # Only enter if spread is above historical mean
            spread_mean = np.mean(self._spread_history[-100:]) if len(self._spread_history) >= 100 else np.mean(self._spread_history)
            spread_std = np.std(self._spread_history[-100:]) if len(self._spread_history) >= 100 else np.std(self._spread_history)

            if spread_std == 0:
                return

            z = (spread - spread_mean) / spread_std

            # Enter when spread is elevated (z > 0.5) -- perp is expensive vs equity
            if z > 0.5 or (len(self._spread_history) < 50):
                # Long leg: equity
                long_notional = portfolio.equity * self.position_size_pct
                long_size = long_notional / long_px
                portfolio.open_position(
                    self._long_sym, "long", long_px,
                    size=long_size,
                    timestamp=timestamp,
                )

                # Short leg: perp (with leverage)
                short_notional = long_notional * self.hedge_ratio
                short_size = short_notional / short_px
                portfolio.open_position(
                    self._short_sym, "short", short_px,
                    size=short_size,
                    timestamp=timestamp,
                )

                self._last_rebalance = timestamp
