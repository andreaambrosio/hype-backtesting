"""Funding Rate Arbitrage -- go short when funding is extremely positive, long when extremely negative.

What it does:
    Fades crowded positioning on Hyperliquid by betting that extreme funding
    rates will snap back to normal. When longs are paying shorts more than
    0.01% per 8h, the market is overleveraged long -- short it. The reverse
    applies when funding is deeply negative.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import numpy as np

from .base import Strategy
from ..engine.portfolio import Portfolio


class FundingRateArb(Strategy):
    name = "Funding Rate Arb"

    def __init__(
        self,
        entry_threshold: float = 0.0003,   # 0.03% per 8h (~40% annualized)
        exit_threshold: float = 0.0001,     # close when funding normalizes
        lookback_periods: int = 24,         # 24 bars for z-score calculation
        position_size_pct: float = 0.15,
        stop_loss_pct: float = 0.03,
    ):
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
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
            if "funding" not in df.columns or len(df) < self.lookback_periods:
                continue

            current_funding = float(df["funding"].iloc[-1])
            price = float(bar[symbol]["close"])

            # Z-score of funding rate
            funding_window = df["funding"].iloc[-self.lookback_periods:]
            mu = funding_window.mean()
            sigma = funding_window.std()
            if sigma == 0:
                continue
            z = (current_funding - mu) / sigma

            # Position management
            if symbol in portfolio.positions:
                pos = portfolio.positions[symbol]
                # Exit when funding normalizes
                if pos.side == "short" and current_funding < self.exit_threshold:
                    portfolio.close_position(symbol, price, timestamp)
                elif pos.side == "long" and current_funding > -self.exit_threshold:
                    portfolio.close_position(symbol, price, timestamp)
            else:
                # Entry signals
                if current_funding > self.entry_threshold and z > 2.0:
                    # Extreme positive funding → short (longs paying shorts)
                    stop = price * (1 + self.stop_loss_pct)
                    portfolio.open_position(
                        symbol, "short", price,
                        pct_of_equity=self.position_size_pct,
                        stop_loss=stop, timestamp=timestamp,
                    )
                elif current_funding < -self.entry_threshold and z < -2.0:
                    # Extreme negative funding → long (shorts paying longs)
                    stop = price * (1 - self.stop_loss_pct)
                    portfolio.open_position(
                        symbol, "long", price,
                        pct_of_equity=self.position_size_pct,
                        stop_loss=stop, timestamp=timestamp,
                    )
