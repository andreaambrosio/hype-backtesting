"""HIP-3 Vault Yield Strategy -- rotate between Hyperliquid vaults based on risk-adjusted yield.

What it does:
    Picks the best-performing HIP-3 vaults and allocates capital to them.
    Each vault is scored on a Sharpe-like metric (return / volatility of
    daily PnL), and capital goes to the top N. Vaults with drawdowns
    exceeding a configurable limit are excluded.

How it works:
    This is a meta-strategy -- it does not trade perps directly but instead
    rotates capital across HIP-3 vaults. In backtest mode it uses
    historical vault PnL data.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import numpy as np

from .base import Strategy
from ..engine.portfolio import Portfolio


class HIP3YieldFarm(Strategy):
    name = "HIP-3 Yield Rotation"

    def __init__(
        self,
        top_n: int = 3,
        rebalance_days: int = 7,
        min_tvl: float = 100_000,
        min_history_days: int = 14,
        max_vault_drawdown: float = 0.10,
        position_size_pct: float = 0.30,
    ):
        self.top_n = top_n
        self.rebalance_days = rebalance_days
        self.min_tvl = min_tvl
        self.min_history_days = min_history_days
        self.max_vault_drawdown = max_vault_drawdown
        self.position_size_pct = position_size_pct
        self._last_rebalance: Any = None
        self._current_vaults: list[str] = []

    def _score_vault(self, df: pd.DataFrame) -> float:
        """Score a vault by its Sharpe-like ratio on daily returns."""
        if len(df) < self.min_history_days:
            return -999.0

        if "account_value" in df.columns:
            returns = df["account_value"].pct_change().dropna()
        elif "close" in df.columns:
            returns = df["close"].pct_change().dropna()
        else:
            return -999.0

        if len(returns) < 7 or returns.std() == 0:
            return -999.0

        # Check max drawdown
        cummax = (1 + returns).cumprod().cummax()
        drawdown = ((1 + returns).cumprod() / cummax - 1).min()
        if drawdown < -self.max_vault_drawdown:
            return -999.0

        # Annualized Sharpe (assuming daily data)
        sharpe = (returns.mean() / returns.std()) * np.sqrt(365)
        return float(sharpe)

    def on_bar(
        self,
        timestamp: Any,
        bar: dict[str, pd.Series],
        lookback: dict[str, pd.DataFrame],
        portfolio: Portfolio,
    ):
        # Check if it's time to rebalance
        should_rebalance = False
        if self._last_rebalance is None:
            should_rebalance = True
        else:
            days_since = (pd.Timestamp(timestamp) - pd.Timestamp(self._last_rebalance)).days
            if days_since >= self.rebalance_days:
                should_rebalance = True

        if not should_rebalance:
            return

        self._last_rebalance = timestamp

        # Score all vaults
        scores = {}
        for symbol in self.symbols:
            if symbol not in lookback:
                continue
            score = self._score_vault(lookback[symbol])
            if score > -999:
                scores[symbol] = score

        # Rank and select top N
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        new_vaults = [sym for sym, _ in ranked[:self.top_n]]

        # Close positions not in new top N
        for sym in list(portfolio.positions.keys()):
            if sym not in new_vaults and sym in bar:
                price = float(bar[sym]["close"]) if "close" in bar[sym].index else float(bar[sym].iloc[0])
                portfolio.close_position(sym, price, timestamp)

        # Open positions in new top N
        for sym in new_vaults:
            if sym not in portfolio.positions and sym in bar:
                price = float(bar[sym]["close"]) if "close" in bar[sym].index else float(bar[sym].iloc[0])
                portfolio.open_position(
                    sym, "long", price,
                    pct_of_equity=self.position_size_pct / self.top_n,
                    timestamp=timestamp,
                )

        self._current_vaults = new_vaults
