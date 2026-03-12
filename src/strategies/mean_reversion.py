"""Mean Reversion -- Bollinger Band + RSI strategy.

What it does:
    Buys oversold dips and sells overbought rallies, using Bollinger Bands
    for price extremes and RSI for momentum confirmation.

How it works:
    Entry: price at lower BB + RSI < 30 --> go long.
           Price at upper BB + RSI > 70 --> go short.
    Exit: price reverts to the middle BB (SMA) or an opposite signal fires.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import numpy as np

from .base import Strategy
from ..engine.portfolio import Portfolio


class MeanReversion(Strategy):
    name = "Mean Reversion (BB + RSI)"

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        position_size_pct: float = 0.15,
        stop_loss_pct: float = 0.04,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.position_size_pct = position_size_pct
        self.stop_loss_pct = stop_loss_pct

    def _calc_rsi(self, series: pd.Series, period: int) -> float:
        if len(series) < period + 1:
            return 50.0
        delta = series.diff().iloc[-period:]
        gain = delta.clip(lower=0).mean()
        loss = -delta.clip(upper=0).mean()
        if loss == 0:
            return 100.0
        rs = gain / loss
        return 100 - (100 / (1 + rs))

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
            if len(df) < self.bb_period + 1:
                continue

            close = df["close"]
            price = float(close.iloc[-1])

            # Bollinger Bands
            sma = float(close.iloc[-self.bb_period:].mean())
            std = float(close.iloc[-self.bb_period:].std())
            upper_bb = sma + self.bb_std * std
            lower_bb = sma - self.bb_std * std

            # RSI
            rsi = self._calc_rsi(close, self.rsi_period)

            if symbol in portfolio.positions:
                pos = portfolio.positions[symbol]
                # Exit at mean (SMA)
                if pos.side == "long" and price >= sma:
                    portfolio.close_position(symbol, price, timestamp)
                elif pos.side == "short" and price <= sma:
                    portfolio.close_position(symbol, price, timestamp)
            else:
                # Long: price at lower BB + oversold RSI
                if price <= lower_bb and rsi < self.rsi_oversold:
                    stop = price * (1 - self.stop_loss_pct)
                    portfolio.open_position(
                        symbol, "long", price,
                        pct_of_equity=self.position_size_pct,
                        stop_loss=stop, timestamp=timestamp,
                    )
                # Short: price at upper BB + overbought RSI
                elif price >= upper_bb and rsi > self.rsi_overbought:
                    stop = price * (1 + self.stop_loss_pct)
                    portfolio.open_position(
                        symbol, "short", price,
                        pct_of_equity=self.position_size_pct,
                        stop_loss=stop, timestamp=timestamp,
                    )
