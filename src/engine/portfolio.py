"""Portfolio and position management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import numpy as np


@dataclass
class Position:
    symbol: str
    side: str           # "long" or "short"
    entry_price: float
    size: float         # in units (e.g. 1.5 BTC)
    entry_time: Any = None
    stop_loss: float | None = None
    take_profit: float | None = None

    @property
    def notional(self) -> float:
        return abs(self.size * self.entry_price)

    def unrealized_pnl(self, current_price: float) -> float:
        if self.side == "long":
            return self.size * (current_price - self.entry_price)
        return self.size * (self.entry_price - current_price)

    def should_stop(self, current_price: float) -> bool:
        if self.stop_loss and self.side == "long" and current_price <= self.stop_loss:
            return True
        if self.stop_loss and self.side == "short" and current_price >= self.stop_loss:
            return True
        if self.take_profit and self.side == "long" and current_price >= self.take_profit:
            return True
        if self.take_profit and self.side == "short" and current_price <= self.take_profit:
            return True
        return False


@dataclass
class Trade:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    entry_time: Any
    exit_time: Any
    pnl: float
    pnl_pct: float
    commission: float


class Portfolio:
    def __init__(
        self,
        initial_capital: float = 100_000.0,
        commission_bps: float = 2.0,
        slippage_bps: float = 1.0,
        max_position_pct: float = 0.25,
        max_drawdown_pct: float = 0.15,
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_bps = commission_bps
        self.slippage_bps = slippage_bps
        self.max_position_pct = max_position_pct
        self.max_drawdown_pct = max_drawdown_pct

        self.positions: dict[str, Position] = {}
        self.closed_trades: list[Trade] = []
        self.equity_curve: list[dict] = []
        self.peak_equity = initial_capital
        self._killed = False

    @property
    def equity(self) -> float:
        return self.cash + sum(
            p.notional for p in self.positions.values()
        )

    @property
    def drawdown(self) -> float:
        if self.peak_equity == 0:
            return 0.0
        return (self.peak_equity - self.equity) / self.peak_equity

    def _apply_slippage(self, price: float, side: str) -> float:
        slip = price * self.slippage_bps / 10_000
        return price + slip if side == "long" else price - slip

    def _commission(self, notional: float) -> float:
        return notional * self.commission_bps / 10_000

    def open_position(
        self,
        symbol: str,
        side: str,
        price: float,
        size: float | None = None,
        pct_of_equity: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        timestamp: Any = None,
    ) -> Position | None:
        if self._killed:
            return None

        fill_price = self._apply_slippage(price, side)

        if pct_of_equity:
            pct = min(pct_of_equity, self.max_position_pct)
            notional = self.equity * pct
            size = notional / fill_price

        if size is None:
            return None

        notional = size * fill_price
        comm = self._commission(notional)

        if notional + comm > self.cash:
            size = (self.cash - comm) / fill_price
            notional = size * fill_price
            comm = self._commission(notional)

        if size <= 0:
            return None

        self.cash -= notional + comm

        pos = Position(
            symbol=symbol,
            side=side,
            entry_price=fill_price,
            size=size,
            entry_time=timestamp,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        self.positions[symbol] = pos
        return pos

    def close_position(self, symbol: str, price: float, timestamp: Any = None) -> Trade | None:
        if symbol not in self.positions:
            return None

        pos = self.positions.pop(symbol)
        exit_side = "short" if pos.side == "long" else "long"
        fill_price = self._apply_slippage(price, exit_side)

        notional = pos.size * fill_price
        comm = self._commission(notional) + self._commission(pos.notional)
        pnl = pos.unrealized_pnl(fill_price) - comm

        self.cash += notional
        pnl_pct = pnl / pos.notional if pos.notional > 0 else 0.0

        trade = Trade(
            symbol=pos.symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=fill_price,
            size=pos.size,
            entry_time=pos.entry_time,
            exit_time=timestamp,
            pnl=pnl,
            pnl_pct=pnl_pct,
            commission=comm,
        )
        self.closed_trades.append(trade)
        return trade

    def update(self, prices: dict[str, float], timestamp: Any = None):
        """Called each bar -- check stops, record equity, check kill switch."""
        for symbol in list(self.positions.keys()):
            if symbol in prices:
                pos = self.positions[symbol]
                if pos.should_stop(prices[symbol]):
                    self.close_position(symbol, prices[symbol], timestamp)

        eq = self.cash + sum(
            pos.size * prices.get(pos.symbol, pos.entry_price)
            for pos in self.positions.values()
        )
        self.peak_equity = max(self.peak_equity, eq)

        self.equity_curve.append({
            "time": timestamp,
            "equity": eq,
            "cash": self.cash,
            "n_positions": len(self.positions),
            "drawdown": (self.peak_equity - eq) / self.peak_equity if self.peak_equity > 0 else 0,
        })

        current_dd = (self.peak_equity - eq) / self.peak_equity if self.peak_equity > 0 else 0
        if current_dd >= self.max_drawdown_pct:
            self._killed = True
            for sym in list(self.positions.keys()):
                if sym in prices:
                    self.close_position(sym, prices[sym], timestamp)

    def get_equity_df(self) -> pd.DataFrame:
        df = pd.DataFrame(self.equity_curve)
        if not df.empty and "time" in df.columns:
            df = df.set_index("time")
        return df

    def get_trades_df(self) -> pd.DataFrame:
        if not self.closed_trades:
            return pd.DataFrame()
        rows = [
            {
                "symbol": t.symbol, "side": t.side,
                "entry_price": t.entry_price, "exit_price": t.exit_price,
                "size": t.size, "entry_time": t.entry_time, "exit_time": t.exit_time,
                "pnl": t.pnl, "pnl_pct": t.pnl_pct, "commission": t.commission,
            }
            for t in self.closed_trades
        ]
        return pd.DataFrame(rows)
