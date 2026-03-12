"""Core backtesting engine -- feeds data bar-by-bar to strategies."""

from __future__ import annotations

import pandas as pd
from rich.console import Console
from rich.table import Table

from .portfolio import Portfolio
from ..strategies.base import Strategy
from ..analytics.metrics import PerformanceMetrics

console = Console()


class BacktestEngine:
    def __init__(
        self,
        strategy: Strategy,
        data: dict[str, pd.DataFrame],
        initial_capital: float = 100_000.0,
        commission_bps: float = 2.0,
        slippage_bps: float = 1.0,
        max_position_pct: float = 0.25,
        max_drawdown_pct: float = 0.15,
    ):
        """
        Args:
            strategy: Strategy instance with on_bar() method.
            data: dict of {symbol: DataFrame} with OHLCV columns + any extra signals.
                  All DataFrames must have a DatetimeIndex.
        """
        self.strategy = strategy
        self.data = data
        self.portfolio = Portfolio(
            initial_capital=initial_capital,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            max_position_pct=max_position_pct,
            max_drawdown_pct=max_drawdown_pct,
        )
        self._aligned: pd.DataFrame | None = None

    def _align_data(self) -> pd.DatetimeIndex:
        """Find common timestamps across all symbols."""
        indices = [df.index for df in self.data.values()]
        common = indices[0]
        for idx in indices[1:]:
            common = common.intersection(idx)
        return common.sort_values()

    def run(self) -> BacktestResult:
        """Execute the backtest bar by bar."""
        timestamps = self._align_data()
        symbols = list(self.data.keys())

        console.print(f"[bold cyan]Running backtest:[/] {self.strategy.name}")
        console.print(f"  Symbols: {', '.join(symbols)}")
        console.print(f"  Period: {timestamps[0]} → {timestamps[-1]} ({len(timestamps)} bars)")
        console.print(f"  Capital: ${self.portfolio.initial_capital:,.0f}")
        console.print()

        self.strategy.initialize(symbols, self.portfolio)

        for i, ts in enumerate(timestamps):
            bar = {}
            prices = {}
            for sym in symbols:
                if ts in self.data[sym].index:
                    row = self.data[sym].loc[ts]
                    bar[sym] = row
                    prices[sym] = float(row["close"]) if "close" in row.index else float(row.iloc[0])

            # Feed lookback window to strategy
            lookback = {}
            for sym in symbols:
                mask = self.data[sym].index <= ts
                lookback[sym] = self.data[sym][mask]

            self.strategy.on_bar(ts, bar, lookback, self.portfolio)
            self.portfolio.update(prices, ts)

            if self.portfolio._killed:
                console.print(f"[bold red]KILL SWITCH[/] triggered at {ts} -- max drawdown breached")
                break

        # Close any remaining positions at last price
        for sym in list(self.portfolio.positions.keys()):
            if sym in self.data and len(self.data[sym]) > 0:
                last_price = float(self.data[sym]["close"].iloc[-1])
                self.portfolio.close_position(sym, last_price, timestamps[-1])

        metrics = PerformanceMetrics(self.portfolio)
        result = BacktestResult(
            strategy_name=self.strategy.name,
            portfolio=self.portfolio,
            metrics=metrics,
        )
        result.print_summary()
        return result


class BacktestResult:
    def __init__(self, strategy_name: str, portfolio: Portfolio, metrics: PerformanceMetrics):
        self.strategy_name = strategy_name
        self.portfolio = portfolio
        self.metrics = metrics

    @property
    def equity_curve(self) -> pd.DataFrame:
        return self.portfolio.get_equity_df()

    @property
    def trades(self) -> pd.DataFrame:
        return self.portfolio.get_trades_df()

    def print_summary(self):
        m = self.metrics.compute()

        table = Table(title=f"Backtest Results: {self.strategy_name}", show_lines=True)
        table.add_column("Metric", style="cyan", width=25)
        table.add_column("Value", style="bold white", justify="right", width=20)

        formatters = {
            "total_return": lambda v: f"{v:+.2%}",
            "cagr": lambda v: f"{v:+.2%}",
            "sharpe_ratio": lambda v: f"{v:.3f}",
            "sortino_ratio": lambda v: f"{v:.3f}",
            "calmar_ratio": lambda v: f"{v:.3f}",
            "max_drawdown": lambda v: f"{v:.2%}",
            "max_drawdown_duration": lambda v: f"{v} days",
            "win_rate": lambda v: f"{v:.1%}",
            "profit_factor": lambda v: f"{v:.2f}",
            "avg_trade_pnl": lambda v: f"${v:,.2f}",
            "avg_winner": lambda v: f"${v:,.2f}",
            "avg_loser": lambda v: f"${v:,.2f}",
            "total_trades": lambda v: f"{v}",
            "total_commission": lambda v: f"${v:,.2f}",
            "final_equity": lambda v: f"${v:,.2f}",
        }

        for key, value in m.items():
            label = key.replace("_", " ").title()
            fmt = formatters.get(key, lambda v: f"{v}")
            table.add_row(label, fmt(value))

        console.print(table)
