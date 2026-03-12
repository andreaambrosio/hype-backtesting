"""Basis Mean Reversion -- trade dislocations between perp mark and oracle.

What it does:
    Profits from short-lived gaps between the perp mark price and the oracle.
    During the HIP-3 Silver crash, basis hit 463 bps, stayed above 400 bps
    for only 95 seconds, and snapped back below 50 bps within 19 minutes.

How it works:
    1. Tracks the perp premium vs oracle in real time
    2. When the premium spikes past a threshold, shorts the perp
       (betting it converges back to the oracle)
    3. Sizes the trade based on how large the dislocation is and
       how fast similar gaps have closed historically
    4. Exits on a timer if the reversion does not happen within
       the expected window

This is a statistical arbitrage on the funding/basis mechanism itself.
The edge shrinks as HIP-3 markets mature and order-book depth grows.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import numpy as np

from .base import Strategy
from ..engine.portfolio import Portfolio


class BasisReversion(Strategy):
    name = "Basis Dislocation Reversion"

    def __init__(
        self,
        entry_dislocation_bps: float = 50.0,     # enter at 50+ bps dislocation
        exit_dislocation_bps: float = 10.0,       # exit when basis compresses to 10 bps
        max_hold_bars: int = 60,                   # max hold 60 bars (e.g., 60 min)
        lookback_bars: int = 100,                  # for premium distribution
        percentile_entry: float = 0.95,            # only trade 95th pctile dislocations
        base_position_pct: float = 0.10,
        dislocation_scalar: bool = True,           # scale size with dislocation magnitude
        max_position_pct: float = 0.25,
        stop_loss_bps: float = 200.0,              # hard stop at 200 bps further dislocation
    ):
        self.entry_dislocation_bps = entry_dislocation_bps
        self.exit_dislocation_bps = exit_dislocation_bps
        self.max_hold_bars = max_hold_bars
        self.lookback_bars = lookback_bars
        self.percentile_entry = percentile_entry
        self.base_position_pct = base_position_pct
        self.dislocation_scalar = dislocation_scalar
        self.max_position_pct = max_position_pct
        self.stop_loss_bps = stop_loss_bps
        self._entry_bar: dict[str, int] = {}
        self._bar_count: int = 0

    def _premium_bps(self, df: pd.DataFrame) -> pd.Series | None:
        """Compute perp premium over oracle in bps."""
        if "premium" in df.columns:
            return df["premium"] * 10_000
        if "mark_price" in df.columns and "oracle_price" in df.columns:
            return ((df["mark_price"] - df["oracle_price"]) / df["oracle_price"]) * 10_000
        return None

    def on_bar(
        self,
        timestamp: Any,
        bar: dict[str, pd.Series],
        lookback: dict[str, pd.DataFrame],
        portfolio: Portfolio,
    ):
        self._bar_count += 1

        for symbol in self.symbols:
            if symbol not in bar or symbol not in lookback:
                continue

            df = lookback[symbol]
            premium_series = self._premium_bps(df)
            if premium_series is None or len(premium_series) < self.lookback_bars:
                continue

            current_premium = float(premium_series.iloc[-1])
            abs_premium = abs(current_premium)
            price = float(bar[symbol]["close"])

            # Historical premium distribution
            hist = premium_series.iloc[-self.lookback_bars:]
            abs_hist = hist.abs()
            threshold = max(
                self.entry_dislocation_bps,
                float(abs_hist.quantile(self.percentile_entry))
            )

            if symbol in portfolio.positions:
                pos = portfolio.positions[symbol]
                bars_held = self._bar_count - self._entry_bar.get(symbol, self._bar_count)

                # Exit conditions
                should_exit = False

                # 1. Basis compressed (take profit)
                if abs_premium < self.exit_dislocation_bps:
                    should_exit = True

                # 2. Time decay -- held too long, reversion not happening
                if bars_held >= self.max_hold_bars:
                    should_exit = True

                # 3. Further dislocation (stop loss)
                if pos.side == "short" and current_premium > self.stop_loss_bps:
                    should_exit = True
                elif pos.side == "long" and current_premium < -self.stop_loss_bps:
                    should_exit = True

                if should_exit:
                    portfolio.close_position(symbol, price, timestamp)
                    self._entry_bar.pop(symbol, None)

            else:
                # Entry: trade extreme dislocations
                if abs_premium < threshold:
                    continue

                # Size: scale with dislocation magnitude
                if self.dislocation_scalar:
                    scale = min(abs_premium / self.entry_dislocation_bps, 3.0)
                    size_pct = min(self.base_position_pct * scale, self.max_position_pct)
                else:
                    size_pct = self.base_position_pct

                if current_premium > 0:
                    # Perp trading above oracle → short, expect reversion down
                    stop = price * (1 + self.stop_loss_bps / 10_000)
                    portfolio.open_position(
                        symbol, "short", price,
                        pct_of_equity=size_pct,
                        stop_loss=stop,
                        timestamp=timestamp,
                    )
                else:
                    # Perp trading below oracle → long, expect reversion up
                    stop = price * (1 - self.stop_loss_bps / 10_000)
                    portfolio.open_position(
                        symbol, "long", price,
                        pct_of_equity=size_pct,
                        stop_loss=stop,
                        timestamp=timestamp,
                    )
                self._entry_bar[symbol] = self._bar_count
