"""Volatility Breakout -- trade range expansions confirmed by volume.

What it does:
    Catches breakouts from consolidation ranges and rides the trend.
    In the current regime, large moves tend to follow through rather
    than revert, so the strategy enters on the breakout and trails
    an ATR-based stop behind the move.

How it works:
    Entry: price breaks above/below the N-bar high/low AND volume
           exceeds K times the average volume.
    Exit: ATR-based trailing stop OR an opposite-direction breakout.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import numpy as np

from .base import Strategy
from ..engine.portfolio import Portfolio


class VolatilityBreakout(Strategy):
    name = "Volatility Breakout"

    def __init__(
        self,
        breakout_period: int = 24,        # look for breakout of 24-bar range
        volume_threshold: float = 1.8,     # volume must be 1.8x average
        atr_period: int = 14,
        atr_stop_mult: float = 2.5,       # trail at 2.5 ATR
        position_size_pct: float = 0.15,
        cooldown_bars: int = 6,            # wait 6 bars after exit before re-entry
        max_positions: int = 3,
    ):
        self.breakout_period = breakout_period
        self.volume_threshold = volume_threshold
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.position_size_pct = position_size_pct
        self.cooldown_bars = cooldown_bars
        self.max_positions = max_positions
        self._trailing: dict[str, float] = {}
        self._cooldowns: dict[str, int] = {}
        self._bar_count = 0

    def _atr(self, df: pd.DataFrame) -> float:
        n = self.atr_period
        if len(df) < n + 1:
            return 0.0
        h = df["high"].iloc[-n:]
        l = df["low"].iloc[-n:]
        c = df["close"].iloc[-n - 1:-1]
        tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
        return float(tr.mean())

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
            if len(df) < self.breakout_period + 2:
                continue

            price = float(bar[symbol]["close"])
            atr = self._atr(df)
            if atr == 0:
                continue

            # Range: highest high and lowest low over breakout period (excluding current bar)
            range_high = float(df["high"].iloc[-self.breakout_period - 1:-1].max())
            range_low = float(df["low"].iloc[-self.breakout_period - 1:-1].min())

            # Volume check
            vol_ok = True
            if "volume" in df.columns:
                avg_vol = float(df["volume"].iloc[-self.breakout_period:].mean())
                curr_vol = float(bar[symbol].get("volume", 0))
                vol_ok = avg_vol == 0 or curr_vol > avg_vol * self.volume_threshold

            # Manage existing positions with ATR trailing stop
            if symbol in portfolio.positions:
                pos = portfolio.positions[symbol]
                if pos.side == "long":
                    self._trailing[symbol] = max(self._trailing.get(symbol, price), price)
                    stop = self._trailing[symbol] - self.atr_stop_mult * atr
                    if price < stop:
                        portfolio.close_position(symbol, price, timestamp)
                        self._trailing.pop(symbol, None)
                        self._cooldowns[symbol] = self._bar_count
                elif pos.side == "short":
                    self._trailing[symbol] = min(self._trailing.get(symbol, price), price)
                    stop = self._trailing[symbol] + self.atr_stop_mult * atr
                    if price > stop:
                        portfolio.close_position(symbol, price, timestamp)
                        self._trailing.pop(symbol, None)
                        self._cooldowns[symbol] = self._bar_count
                continue

            # Cooldown check
            last_exit = self._cooldowns.get(symbol, -999)
            if self._bar_count - last_exit < self.cooldown_bars:
                continue

            # Max positions check
            if len(portfolio.positions) >= self.max_positions:
                continue

            # Breakout entries
            if price > range_high and vol_ok:
                stop = price - self.atr_stop_mult * atr
                portfolio.open_position(
                    symbol, "long", price,
                    pct_of_equity=self.position_size_pct,
                    stop_loss=stop,
                    timestamp=timestamp,
                )
                self._trailing[symbol] = price

            elif price < range_low and vol_ok:
                stop = price + self.atr_stop_mult * atr
                portfolio.open_position(
                    symbol, "short", price,
                    pct_of_equity=self.position_size_pct,
                    stop_loss=stop,
                    timestamp=timestamp,
                )
                self._trailing[symbol] = price
