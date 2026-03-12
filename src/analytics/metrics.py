"""Performance analytics -- all the metrics that matter."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..engine.portfolio import Portfolio


class PerformanceMetrics:
    def __init__(self, portfolio: Portfolio, risk_free_rate: float = 0.05):
        self.portfolio = portfolio
        self.rf = risk_free_rate

    def compute(self) -> dict:
        eq = self.portfolio.get_equity_df()
        trades_df = self.portfolio.get_trades_df()

        if eq.empty:
            return {"error": "no data"}

        equity = eq["equity"]
        returns = equity.pct_change().dropna()

        # Core returns
        total_return = (equity.iloc[-1] / self.portfolio.initial_capital) - 1

        # CAGR
        if hasattr(equity.index, 'to_series'):
            try:
                days = (equity.index[-1] - equity.index[0]).days
            except (TypeError, AttributeError):
                days = len(equity)
        else:
            days = len(equity)
        years = max(days / 365.25, 1 / 365.25)
        cagr = (1 + total_return) ** (1 / years) - 1 if total_return > -1 else -1.0

        # Volatility
        if len(returns) > 1:
            daily_vol = float(returns.std())
            annual_vol = daily_vol * np.sqrt(365)
        else:
            daily_vol = annual_vol = 0.0

        # Sharpe
        if annual_vol > 0:
            sharpe = (cagr - self.rf) / annual_vol
        else:
            sharpe = 0.0

        # Sortino
        downside = returns[returns < 0]
        if len(downside) > 0:
            downside_vol = float(downside.std()) * np.sqrt(365)
            sortino = (cagr - self.rf) / downside_vol if downside_vol > 0 else 0.0
        else:
            sortino = float("inf") if cagr > self.rf else 0.0

        # Max drawdown
        peak = equity.cummax()
        drawdown = (equity - peak) / peak
        max_dd = float(drawdown.min())

        # Max drawdown duration
        dd_duration = 0
        if max_dd < 0:
            underwater = drawdown < 0
            groups = (~underwater).cumsum()
            if underwater.any():
                dd_lengths = underwater.groupby(groups).sum()
                dd_duration = int(dd_lengths.max()) if len(dd_lengths) > 0 else 0

        # Calmar
        calmar = cagr / abs(max_dd) if max_dd != 0 else 0.0

        # Trade stats
        n_trades = len(trades_df)
        if n_trades > 0:
            winners = trades_df[trades_df["pnl"] > 0]
            losers = trades_df[trades_df["pnl"] <= 0]
            win_rate = len(winners) / n_trades
            avg_trade = float(trades_df["pnl"].mean())
            avg_winner = float(winners["pnl"].mean()) if len(winners) > 0 else 0.0
            avg_loser = float(losers["pnl"].mean()) if len(losers) > 0 else 0.0
            gross_profit = float(winners["pnl"].sum()) if len(winners) > 0 else 0.0
            gross_loss = abs(float(losers["pnl"].sum())) if len(losers) > 0 else 0.0
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
            total_commission = float(trades_df["commission"].sum())
        else:
            win_rate = avg_trade = avg_winner = avg_loser = 0.0
            profit_factor = total_commission = 0.0

        return {
            "total_return": total_return,
            "cagr": cagr,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "calmar_ratio": calmar,
            "max_drawdown": abs(max_dd),
            "max_drawdown_duration": dd_duration,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_trade_pnl": avg_trade,
            "avg_winner": avg_winner,
            "avg_loser": avg_loser,
            "total_trades": n_trades,
            "total_commission": total_commission,
            "final_equity": float(equity.iloc[-1]),
        }
