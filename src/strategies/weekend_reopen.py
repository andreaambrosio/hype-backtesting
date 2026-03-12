"""Weekend-to-Reopen Positioning -- trade the Sunday auction gap.

What it does:
    Exploits the price gap between Friday's close and Monday's reopen.
    From HIP-3 Silver data: COMEX closed Fri 22:00 UTC, reopened Sun 23:00 UTC,
    while Hyperliquid traded continuously (175k trades, $257M notional).
    Sunday's last internal price was closer to Monday's open than Friday's close,
    but across HIP-3 equities the pre-open HL price only predicted the oracle
    open 50.7% of the time (median improvement +0.4 bps).

How it works:
    1. Detects weekend regime (no oracle updates / low volume)
    2. Tracks how far price has drifted from Friday's close
    3. Positions for mean-reversion back to Friday's close OR continuation
    4. Closes everything at reopen when the oracle resumes

The idea is that weekend prices tend to overshoot because liquidity is thin
and flow is mostly retail; the reopen auction then pulls price back toward
fundamentals. Alternatively, if the HL weekend price carries real information,
the strategy can ride the move into reopen.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import numpy as np

from .base import Strategy
from ..engine.portfolio import Portfolio


class WeekendReopen(Strategy):
    name = "Weekend-to-Reopen Arb"

    def __init__(
        self,
        drift_threshold_pct: float = 0.005,  # 0.5% drift from Friday close to act
        reversion_pct: float = 0.60,           # expect 60% reversion of weekend move
        position_size_pct: float = 0.10,
        stop_loss_pct: float = 0.02,
        mode: str = "mean_reversion",          # "mean_reversion" or "momentum"
        weekend_vol_discount: float = 0.75,    # weekend vol is ~75% of weekday
    ):
        self.drift_threshold = drift_threshold_pct
        self.reversion_pct = reversion_pct
        self.position_size_pct = position_size_pct
        self.stop_loss_pct = stop_loss_pct
        self.mode = mode
        self.weekend_vol_discount = weekend_vol_discount
        self._friday_close: dict[str, float] = {}
        self._positioned: dict[str, bool] = {}
        self._in_weekend: bool = False

    def _is_weekend(self, ts: pd.Timestamp) -> bool:
        """Check if timestamp falls in weekend regime.
        Friday 22:00 UTC to Sunday 23:00 UTC for COMEX-linked.
        Friday 16:00 ET (21:00 UTC) to Monday 09:30 ET (14:30 UTC) for equities.
        """
        if isinstance(ts, str):
            ts = pd.Timestamp(ts)
        dow = ts.dayofweek  # Monday=0, Sunday=6
        hour = ts.hour

        # Saturday or Sunday early
        if dow in (5, 6):
            return True
        # Friday late
        if dow == 4 and hour >= 22:
            return True
        # Sunday late / Monday early
        if dow == 0 and hour < 14:
            return True
        return False

    def _is_pre_reopen(self, ts: pd.Timestamp) -> bool:
        """Last 2 hours before reopen (Sunday 21:00-23:00 UTC)."""
        if isinstance(ts, str):
            ts = pd.Timestamp(ts)
        return ts.dayofweek == 6 and ts.hour >= 21

    def on_bar(
        self,
        timestamp: Any,
        bar: dict[str, pd.Series],
        lookback: dict[str, pd.DataFrame],
        portfolio: Portfolio,
    ):
        ts = pd.Timestamp(timestamp) if not isinstance(timestamp, pd.Timestamp) else timestamp
        is_weekend = self._is_weekend(ts)
        was_weekend = self._in_weekend
        self._in_weekend = is_weekend

        for symbol in self.symbols:
            if symbol not in bar or symbol not in lookback:
                continue

            price = float(bar[symbol]["close"])

            # Capture Friday close
            if not is_weekend and ts.dayofweek == 4 and ts.hour >= 20:
                self._friday_close[symbol] = price

            # Reopen: close all weekend positions
            if was_weekend and not is_weekend:
                if symbol in portfolio.positions:
                    portfolio.close_position(symbol, price, timestamp)
                    self._positioned[symbol] = False
                continue

            # During weekend: look for positioning opportunity
            if not is_weekend:
                continue

            friday_px = self._friday_close.get(symbol)
            if friday_px is None or friday_px == 0:
                continue

            drift = (price - friday_px) / friday_px

            if symbol in portfolio.positions:
                pos = portfolio.positions[symbol]
                # Pre-reopen: tighten stops
                if self._is_pre_reopen(ts):
                    if self.mode == "mean_reversion":
                        # If price has already reverted, take profit
                        if pos.side == "short" and price <= friday_px:
                            portfolio.close_position(symbol, price, timestamp)
                        elif pos.side == "long" and price >= friday_px:
                            portfolio.close_position(symbol, price, timestamp)
                continue

            if self._positioned.get(symbol, False):
                continue

            # Need sufficient drift to act
            if abs(drift) < self.drift_threshold:
                continue

            if self.mode == "mean_reversion":
                # Drift up → short (expect reversion)
                if drift > 0:
                    stop = price * (1 + self.stop_loss_pct)
                    portfolio.open_position(
                        symbol, "short", price,
                        pct_of_equity=self.position_size_pct,
                        stop_loss=stop,
                        timestamp=timestamp,
                    )
                else:
                    stop = price * (1 - self.stop_loss_pct)
                    portfolio.open_position(
                        symbol, "long", price,
                        pct_of_equity=self.position_size_pct,
                        stop_loss=stop,
                        timestamp=timestamp,
                    )
            else:  # momentum
                if drift > 0:
                    stop = price * (1 - self.stop_loss_pct)
                    portfolio.open_position(
                        symbol, "long", price,
                        pct_of_equity=self.position_size_pct,
                        stop_loss=stop,
                        timestamp=timestamp,
                    )
                else:
                    stop = price * (1 + self.stop_loss_pct)
                    portfolio.open_position(
                        symbol, "short", price,
                        pct_of_equity=self.position_size_pct,
                        stop_loss=stop,
                        timestamp=timestamp,
                    )

            self._positioned[symbol] = True
