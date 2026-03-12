"""Adaptive Regime Strategy -- switches between momentum and mean-reversion
depending on what the market is doing.

What it does:
    Instead of committing to a single model, this strategy detects the
    current market regime and picks the right sub-strategy automatically.

How it works:
    Regime detection:
    - Trending: ADX > 25 AND directional movement is sustained
    - Mean-reverting: ADX < 20 AND price oscillating within a range
    - Volatile: ATR expanding rapidly

    Trending regime  --> MA crossover (momentum)
    Ranging regime   --> Bollinger Bands + RSI (mean reversion)
    Volatile regime  --> reduce size or sit out
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import numpy as np

from .base import Strategy
from ..engine.portfolio import Portfolio


class AdaptiveRegime(Strategy):
    name = "Adaptive Regime"

    def __init__(
        self,
        adx_period: int = 14,
        adx_trend_threshold: float = 25.0,
        adx_range_threshold: float = 20.0,
        fast_ma: int = 8,
        slow_ma: int = 24,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        position_size_pct: float = 0.15,
        vol_regime_size: float = 0.08,   # reduced size in volatile regime
        atr_expansion: float = 1.5,       # ATR must expand 1.5x for vol regime
        trailing_stop_atr: float = 2.0,
    ):
        self.adx_period = adx_period
        self.adx_trend = adx_trend_threshold
        self.adx_range = adx_range_threshold
        self.fast_ma = fast_ma
        self.slow_ma = slow_ma
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_os = rsi_oversold
        self.rsi_ob = rsi_overbought
        self.position_size_pct = position_size_pct
        self.vol_size = vol_regime_size
        self.atr_expansion = atr_expansion
        self.trailing_atr = trailing_stop_atr
        self._trailing: dict[str, float] = {}

    def _calc_adx(self, df: pd.DataFrame) -> tuple[float, float, float]:
        """Calculate ADX, +DI, -DI."""
        n = self.adx_period
        if len(df) < n * 2:
            return 0.0, 0.0, 0.0

        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        plus_dm = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)

        # When plus_dm < minus_dm, plus_dm = 0 and vice versa
        mask = plus_dm > minus_dm
        plus_dm = plus_dm.where(mask, 0)
        minus_dm = minus_dm.where(~mask, 0)

        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)

        atr = tr.rolling(n).mean()
        plus_di = 100 * (plus_dm.rolling(n).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(n).mean() / atr)

        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di)).fillna(0)
        adx = dx.rolling(n).mean()

        return float(adx.iloc[-1]), float(plus_di.iloc[-1]), float(minus_di.iloc[-1])

    def _calc_rsi(self, series: pd.Series) -> float:
        if len(series) < self.rsi_period + 1:
            return 50.0
        delta = series.diff().iloc[-self.rsi_period:]
        gain = delta.clip(lower=0).mean()
        loss = -delta.clip(upper=0).mean()
        if loss == 0:
            return 100.0
        return 100 - (100 / (1 + gain / loss))

    def _atr(self, df: pd.DataFrame, period: int = 14) -> float:
        if len(df) < period + 1:
            return 0.0
        h = df["high"].iloc[-period:]
        l = df["low"].iloc[-period:]
        c = df["close"].iloc[-period - 1:-1]
        tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
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
            if len(df) < self.adx_period * 3:
                continue

            price = float(bar[symbol]["close"])
            close = df["close"]
            adx, plus_di, minus_di = self._calc_adx(df)
            atr = self._atr(df)
            atr_prev = self._atr(df.iloc[:-self.adx_period]) if len(df) > self.adx_period * 3 else atr

            # Detect regime
            if atr_prev > 0 and atr / atr_prev > self.atr_expansion:
                regime = "volatile"
            elif adx > self.adx_trend:
                regime = "trending"
            elif adx < self.adx_range:
                regime = "ranging"
            else:
                regime = "neutral"

            size = self.vol_size if regime == "volatile" else self.position_size_pct

            if symbol in portfolio.positions:
                pos = portfolio.positions[symbol]
                # ATR trailing stop for all regimes
                if pos.side == "long":
                    self._trailing[symbol] = max(self._trailing.get(symbol, price), price)
                    if price < self._trailing[symbol] - self.trailing_atr * atr:
                        portfolio.close_position(symbol, price, timestamp)
                        self._trailing.pop(symbol, None)
                elif pos.side == "short":
                    self._trailing[symbol] = min(self._trailing.get(symbol, price), price)
                    if price > self._trailing[symbol] + self.trailing_atr * atr:
                        portfolio.close_position(symbol, price, timestamp)
                        self._trailing.pop(symbol, None)
                continue

            if regime == "trending":
                # MA crossover
                fast = float(close.iloc[-self.fast_ma:].mean())
                slow = float(close.iloc[-self.slow_ma:].mean())
                prev_fast = float(close.iloc[-self.fast_ma - 1:-1].mean())
                prev_slow = float(close.iloc[-self.slow_ma - 1:-1].mean())

                if prev_fast <= prev_slow and fast > slow and plus_di > minus_di:
                    stop = price - self.trailing_atr * atr
                    portfolio.open_position(symbol, "long", price, pct_of_equity=size,
                                           stop_loss=stop, timestamp=timestamp)
                    self._trailing[symbol] = price
                elif prev_fast >= prev_slow and fast < slow and minus_di > plus_di:
                    stop = price + self.trailing_atr * atr
                    portfolio.open_position(symbol, "short", price, pct_of_equity=size,
                                           stop_loss=stop, timestamp=timestamp)
                    self._trailing[symbol] = price

            elif regime == "ranging":
                # BB + RSI
                sma = float(close.iloc[-self.bb_period:].mean())
                std = float(close.iloc[-self.bb_period:].std())
                upper = sma + self.bb_std * std
                lower = sma - self.bb_std * std
                rsi = self._calc_rsi(close)

                if price <= lower and rsi < self.rsi_os:
                    stop = price - self.trailing_atr * atr
                    portfolio.open_position(symbol, "long", price, pct_of_equity=size,
                                           stop_loss=stop, timestamp=timestamp)
                    self._trailing[symbol] = price
                elif price >= upper and rsi > self.rsi_ob:
                    stop = price + self.trailing_atr * atr
                    portfolio.open_position(symbol, "short", price, pct_of_equity=size,
                                           stop_loss=stop, timestamp=timestamp)
                    self._trailing[symbol] = price
