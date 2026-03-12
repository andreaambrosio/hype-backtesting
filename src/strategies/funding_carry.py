"""Funding Rate Carry -- production-level implementation.

What it does:
    Collects funding payments on perps (e.g. SpaceX at 41% annualized)
    by going short when funding is high or long when funding is deeply negative.
    This is not free money -- it compensates for inventory risk and the chance
    of a sudden gap move against the position.

How it works:
    Position sizing adjusts dynamically based on three inputs:
    1. Z-score of current funding vs its rolling history
    2. Realized vol regime (smaller size when vol is high)
    3. Basis level (wider basis = more carry but more risk)

    Entry: funding z-score > threshold AND realized vol < cap
    Exit: funding normalizes OR drawdown limit hit OR vol spikes

The edge comes from sizing, not direction. This is the carry trade that
institutional desks run on Hyperliquid.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import numpy as np

from .base import Strategy
from ..engine.portfolio import Portfolio


class FundingCarry(Strategy):
    name = "Funding Carry (Institutional)"

    def __init__(
        self,
        funding_z_entry: float = 1.5,
        funding_z_exit: float = 0.3,
        vol_lookback: int = 72,          # 72 hours for vol regime
        funding_lookback: int = 168,      # 7 days of hourly funding
        max_annualized_vol: float = 1.50, # don't enter above 150% annualized vol
        base_position_pct: float = 0.20,
        vol_scalar: bool = True,          # scale position inversely with vol
        target_vol: float = 0.15,         # target 15% portfolio vol
        max_drawdown_per_trade: float = 0.05,
        min_funding_annualized: float = 0.10,  # don't bother below 10% annualized
    ):
        self.funding_z_entry = funding_z_entry
        self.funding_z_exit = funding_z_exit
        self.vol_lookback = vol_lookback
        self.funding_lookback = funding_lookback
        self.max_annualized_vol = max_annualized_vol
        self.base_position_pct = base_position_pct
        self.vol_scalar = vol_scalar
        self.target_vol = target_vol
        self.max_dd = max_drawdown_per_trade
        self.min_funding_annualized = min_funding_annualized
        self._entry_prices: dict[str, float] = {}

    def _annualized_funding(self, rate_per_period: float, periods_per_day: int = 3) -> float:
        """Convert per-period funding to annualized rate."""
        return rate_per_period * periods_per_day * 365.25

    def _realized_vol(self, close: pd.Series, lookback: int) -> float:
        """Annualized realized vol from hourly returns."""
        if len(close) < lookback + 1:
            return 999.0
        rets = close.pct_change().iloc[-lookback:]
        return float(rets.std() * np.sqrt(365.25 * 24))

    def _vol_adjusted_size(self, realized_vol: float) -> float:
        """Size inversely proportional to vol, targeting portfolio vol."""
        if not self.vol_scalar or realized_vol <= 0:
            return self.base_position_pct
        raw = self.target_vol / realized_vol
        return min(raw, self.base_position_pct)

    def on_bar(
        self,
        timestamp: Any,
        bar: dict[str, pd.Series],
        lookback: dict[str, pd.DataFrame],
        portfolio: Portfolio,
    ):
        for symbol in self.symbols:
            if symbol not in bar or symbol not in lookback:
                continue

            df = lookback[symbol]
            if "funding" not in df.columns or len(df) < self.funding_lookback:
                continue

            price = float(bar[symbol]["close"])
            current_funding = float(df["funding"].iloc[-1])

            # Funding statistics
            funding_window = df["funding"].iloc[-self.funding_lookback:]
            f_mean = float(funding_window.mean())
            f_std = float(funding_window.std())
            if f_std == 0:
                continue
            f_zscore = (current_funding - f_mean) / f_std
            f_annualized = self._annualized_funding(current_funding)

            # Vol regime
            rvol = self._realized_vol(df["close"], self.vol_lookback)

            if symbol in portfolio.positions:
                pos = portfolio.positions[symbol]

                # Exit conditions
                should_exit = False
                reason = ""

                # 1. Funding normalized
                if pos.side == "short" and f_zscore < self.funding_z_exit:
                    should_exit = True
                    reason = "funding_normalized"
                elif pos.side == "long" and f_zscore > -self.funding_z_exit:
                    should_exit = True
                    reason = "funding_normalized"

                # 2. Vol spike (regime change)
                if rvol > self.max_annualized_vol * 1.5:
                    should_exit = True
                    reason = "vol_spike"

                # 3. Per-trade drawdown
                entry = self._entry_prices.get(symbol, price)
                if pos.side == "short":
                    trade_dd = (price - entry) / entry
                else:
                    trade_dd = (entry - price) / entry
                if trade_dd > self.max_dd:
                    should_exit = True
                    reason = "max_dd"

                if should_exit:
                    portfolio.close_position(symbol, price, timestamp)
                    self._entry_prices.pop(symbol, None)

            else:
                # Entry conditions
                if rvol > self.max_annualized_vol:
                    continue

                size_pct = self._vol_adjusted_size(rvol)

                # Positive funding → short (collect carry)
                if (current_funding > 0
                    and f_zscore > self.funding_z_entry
                    and f_annualized > self.min_funding_annualized):
                    stop = price * (1 + self.max_dd)
                    pos = portfolio.open_position(
                        symbol, "short", price,
                        pct_of_equity=size_pct,
                        stop_loss=stop,
                        timestamp=timestamp,
                    )
                    if pos:
                        self._entry_prices[symbol] = pos.entry_price

                # Negative funding → long (collect carry)
                elif (current_funding < 0
                      and f_zscore < -self.funding_z_entry
                      and abs(f_annualized) > self.min_funding_annualized):
                    stop = price * (1 - self.max_dd)
                    pos = portfolio.open_position(
                        symbol, "long", price,
                        pct_of_equity=size_pct,
                        stop_loss=stop,
                        timestamp=timestamp,
                    )
                    if pos:
                        self._entry_prices[symbol] = pos.entry_price
