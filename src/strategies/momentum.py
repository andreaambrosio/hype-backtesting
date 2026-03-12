"""Cross-Asset Momentum -- dual moving-average crossover with volume confirmation.

What it does:
    Follows trends across crypto and equities using a fast/slow MA crossover.
    Both the lookback periods and volume filter are configurable.

How it works:
    Entry: fast MA crosses above slow MA + volume spike.
    Exit: fast MA crosses below slow MA OR trailing stop hit.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import numpy as np

from .base import Strategy
from ..engine.portfolio import Portfolio


class CrossAssetMomentum(Strategy):
    name = "Cross-Asset Momentum"

    def __init__(
        self,
        fast_period: int = 10,
        slow_period: int = 30,
        volume_mult: float = 1.5,       # volume must be 1.5x avg
        position_size_pct: float = 0.15,
        trailing_stop_pct: float = 0.05,
        atr_period: int = 14,
    ):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.volume_mult = volume_mult
        self.position_size_pct = position_size_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.atr_period = atr_period
        self._trailing_highs: dict[str, float] = {}

    def initialize(self, symbols: list[str], portfolio: Portfolio):
        super().initialize(symbols, portfolio)
        self._trailing_highs = {}

    def _calc_atr(self, df: pd.DataFrame, period: int) -> float:
        if len(df) < period + 1:
            return 0.0
        high = df["high"].iloc[-period:]
        low = df["low"].iloc[-period:]
        close = df["close"].iloc[-period - 1:-1]
        tr = pd.concat([
            high - low,
            (high - close).abs(),
            (low - close).abs(),
        ], axis=1).max(axis=1)
        return float(tr.mean())

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
            if len(df) < self.slow_period + 1:
                continue

            close = df["close"]
            price = float(close.iloc[-1])

            fast_ma = float(close.iloc[-self.fast_period:].mean())
            slow_ma = float(close.iloc[-self.slow_period:].mean())
            prev_fast = float(close.iloc[-self.fast_period - 1:-1].mean())
            prev_slow = float(close.iloc[-self.slow_period - 1:-1].mean())

            # Volume confirmation
            vol_ok = True
            if "volume" in df.columns and len(df) >= self.slow_period:
                avg_vol = float(df["volume"].iloc[-self.slow_period:].mean())
                curr_vol = float(bar[symbol].get("volume", 0))
                vol_ok = curr_vol > avg_vol * self.volume_mult or avg_vol == 0

            # Crossover detection
            bullish_cross = prev_fast <= prev_slow and fast_ma > slow_ma
            bearish_cross = prev_fast >= prev_slow and fast_ma < slow_ma

            if symbol in portfolio.positions:
                pos = portfolio.positions[symbol]

                # Trailing stop logic
                if pos.side == "long":
                    self._trailing_highs[symbol] = max(
                        self._trailing_highs.get(symbol, price), price
                    )
                    trail_stop = self._trailing_highs[symbol] * (1 - self.trailing_stop_pct)
                    if price < trail_stop or bearish_cross:
                        portfolio.close_position(symbol, price, timestamp)
                        self._trailing_highs.pop(symbol, None)

                elif pos.side == "short":
                    self._trailing_highs[symbol] = min(
                        self._trailing_highs.get(symbol, price), price
                    )
                    trail_stop = self._trailing_highs[symbol] * (1 + self.trailing_stop_pct)
                    if price > trail_stop or bullish_cross:
                        portfolio.close_position(symbol, price, timestamp)
                        self._trailing_highs.pop(symbol, None)
            else:
                atr = self._calc_atr(df, self.atr_period)

                if bullish_cross and vol_ok:
                    stop = price - 2 * atr if atr > 0 else price * (1 - self.trailing_stop_pct)
                    portfolio.open_position(
                        symbol, "long", price,
                        pct_of_equity=self.position_size_pct,
                        stop_loss=stop, timestamp=timestamp,
                    )
                    self._trailing_highs[symbol] = price

                elif bearish_cross and vol_ok:
                    stop = price + 2 * atr if atr > 0 else price * (1 + self.trailing_stop_pct)
                    portfolio.open_position(
                        symbol, "short", price,
                        pct_of_equity=self.position_size_pct,
                        stop_loss=stop, timestamp=timestamp,
                    )
                    self._trailing_highs[symbol] = price
