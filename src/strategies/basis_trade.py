"""Basis Trade -- capture the spread between perp mark price and oracle (spot) price.

What it does:
    Earns yield from the gap between the perp mark price and the oracle.
    When the perp premium is high (mark >> oracle), shorting the perp collects
    that spread. Paired with a spot long hedge this becomes delta-neutral.
    In backtest the strategy runs the single-leg (perp only) using premium
    as the signal.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import numpy as np

from .base import Strategy
from ..engine.portfolio import Portfolio


class BasisTrade(Strategy):
    name = "Basis Trade"

    def __init__(
        self,
        premium_entry: float = 0.002,     # enter when premium > 0.2%
        premium_exit: float = 0.0005,      # exit when premium normalizes
        lookback_periods: int = 48,
        position_size_pct: float = 0.20,
        stop_loss_pct: float = 0.025,
    ):
        self.premium_entry = premium_entry
        self.premium_exit = premium_exit
        self.lookback_periods = lookback_periods
        self.position_size_pct = position_size_pct
        self.stop_loss_pct = stop_loss_pct

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
            if "premium" not in df.columns or len(df) < self.lookback_periods:
                continue

            current_premium = float(df["premium"].iloc[-1])
            price = float(bar[symbol]["close"])

            # Rolling premium stats
            premium_window = df["premium"].iloc[-self.lookback_periods:]
            premium_pctile = (premium_window < current_premium).mean()

            if symbol in portfolio.positions:
                pos = portfolio.positions[symbol]
                # Close short when premium collapses
                if pos.side == "short" and current_premium < self.premium_exit:
                    portfolio.close_position(symbol, price, timestamp)
                # Close long when negative premium normalizes
                elif pos.side == "long" and current_premium > -self.premium_exit:
                    portfolio.close_position(symbol, price, timestamp)
            else:
                # Extreme positive premium → short perp (collect basis)
                if current_premium > self.premium_entry and premium_pctile > 0.9:
                    stop = price * (1 + self.stop_loss_pct)
                    portfolio.open_position(
                        symbol, "short", price,
                        pct_of_equity=self.position_size_pct,
                        stop_loss=stop, timestamp=timestamp,
                    )
                # Extreme negative premium → long perp (discount)
                elif current_premium < -self.premium_entry and premium_pctile < 0.1:
                    stop = price * (1 - self.stop_loss_pct)
                    portfolio.open_position(
                        symbol, "long", price,
                        pct_of_equity=self.position_size_pct,
                        stop_loss=stop, timestamp=timestamp,
                    )
