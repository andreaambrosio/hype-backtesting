"""Cross-Asset Relative Strength -- long the strongest, short the weakest.

What it does:
    Ranks a universe of assets by recent performance and bets that
    winners keep winning while losers keep losing. Works across
    both crypto and equities.

How it works:
    At each rebalance:
    1. Rank all assets by their N-period return
    2. Go long the top K, short the bottom K
    3. Size each leg inversely with realized vol (risk-parity weighting)
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import numpy as np

from .base import Strategy
from ..engine.portfolio import Portfolio


class RelativeStrength(Strategy):
    name = "Cross-Asset Relative Strength"

    def __init__(
        self,
        ranking_period: int = 72,     # rank on 72-bar (3 day) return
        rebalance_bars: int = 24,     # rebalance every 24 bars
        top_n: int = 2,               # long top 2
        bottom_n: int = 2,            # short bottom 2
        vol_lookback: int = 48,
        position_size_pct: float = 0.12,
        risk_parity: bool = True,
    ):
        self.ranking_period = ranking_period
        self.rebalance_bars = rebalance_bars
        self.top_n = top_n
        self.bottom_n = bottom_n
        self.vol_lookback = vol_lookback
        self.position_size_pct = position_size_pct
        self.risk_parity = risk_parity
        self._bar_count = 0
        self._last_rebalance = -999

    def on_bar(
        self,
        timestamp: Any,
        bar: dict[str, pd.Series],
        lookback: dict[str, pd.DataFrame],
        portfolio: Portfolio,
    ):
        self._bar_count += 1

        if self._bar_count - self._last_rebalance < self.rebalance_bars:
            return

        # Compute returns and vol for all assets
        scores = {}
        vols = {}
        for symbol in self.symbols:
            if symbol not in lookback:
                continue
            df = lookback[symbol]
            if len(df) < max(self.ranking_period, self.vol_lookback) + 1:
                continue

            ret = float(df["close"].iloc[-1] / df["close"].iloc[-self.ranking_period] - 1)
            rvol = float(df["close"].pct_change().iloc[-self.vol_lookback:].std())
            if rvol == 0:
                continue

            scores[symbol] = ret
            vols[symbol] = rvol

        if len(scores) < self.top_n + self.bottom_n:
            return

        # Rank
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        longs = [s for s, _ in ranked[:self.top_n]]
        shorts = [s for s, _ in ranked[-self.bottom_n:]]

        # Close positions not in new allocation
        for sym in list(portfolio.positions.keys()):
            if sym not in longs and sym not in shorts:
                if sym in bar:
                    px = float(bar[sym]["close"]) if "close" in bar[sym].index else float(bar[sym].iloc[0])
                    portfolio.close_position(sym, px, timestamp)

        # Open new positions
        for sym in longs:
            if sym not in portfolio.positions and sym in bar:
                px = float(bar[sym]["close"]) if "close" in bar[sym].index else float(bar[sym].iloc[0])
                size_pct = self.position_size_pct
                if self.risk_parity and sym in vols:
                    target_vol = 0.15
                    size_pct = min(target_vol / (vols[sym] * np.sqrt(365.25 * 24)), self.position_size_pct)
                portfolio.open_position(sym, "long", px, pct_of_equity=size_pct, timestamp=timestamp)

        for sym in shorts:
            if sym not in portfolio.positions and sym in bar:
                px = float(bar[sym]["close"]) if "close" in bar[sym].index else float(bar[sym].iloc[0])
                size_pct = self.position_size_pct
                if self.risk_parity and sym in vols:
                    target_vol = 0.15
                    size_pct = min(target_vol / (vols[sym] * np.sqrt(365.25 * 24)), self.position_size_pct)
                portfolio.open_position(sym, "short", px, pct_of_equity=size_pct, timestamp=timestamp)

        self._last_rebalance = self._bar_count
