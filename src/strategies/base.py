"""Base strategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from ..engine.portfolio import Portfolio


class Strategy(ABC):
    name: str = "BaseStrategy"

    def initialize(self, symbols: list[str], portfolio: Portfolio):
        """Called once before backtest starts. Override for setup."""
        self.symbols = symbols

    @abstractmethod
    def on_bar(
        self,
        timestamp: Any,
        bar: dict[str, pd.Series],
        lookback: dict[str, pd.DataFrame],
        portfolio: Portfolio,
    ):
        """Called on every bar.

        Args:
            timestamp: Current bar timestamp.
            bar: {symbol: Series} with current bar data (open, high, low, close, volume, ...).
            lookback: {symbol: DataFrame} with all historical data up to current bar.
            portfolio: Portfolio object -- call open_position / close_position on it.
        """
        ...
