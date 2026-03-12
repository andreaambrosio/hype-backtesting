"""Backtest visualization -- equity curves, drawdown, trade analysis."""

from __future__ import annotations

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
import pandas as pd
import numpy as np


def plot_backtest(equity_df: pd.DataFrame, trades_df: pd.DataFrame, title: str = "Backtest"):
    """Generate a full backtest report chart."""
    sns.set_theme(style="dark")
    fig, axes = plt.subplots(4, 1, figsize=(16, 20), gridspec_kw={"height_ratios": [3, 1.5, 1.5, 1.5]})
    fig.suptitle(title, fontsize=18, fontweight="bold", color="white", y=0.98)
    fig.patch.set_facecolor("#0a0a0a")

    for ax in axes:
        ax.set_facecolor("#0a0a0a")
        ax.tick_params(colors="#888888")
        ax.spines["bottom"].set_color("#333333")
        ax.spines["left"].set_color("#333333")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    # 1. Equity curve
    ax1 = axes[0]
    ax1.plot(equity_df.index, equity_df["equity"], color="#00ff88", linewidth=1.5, label="Portfolio")
    ax1.axhline(y=equity_df["equity"].iloc[0], color="#555555", linestyle="--", linewidth=0.8, label="Initial Capital")
    ax1.fill_between(equity_df.index, equity_df["equity"].iloc[0], equity_df["equity"],
                      where=equity_df["equity"] >= equity_df["equity"].iloc[0],
                      alpha=0.15, color="#00ff88")
    ax1.fill_between(equity_df.index, equity_df["equity"].iloc[0], equity_df["equity"],
                      where=equity_df["equity"] < equity_df["equity"].iloc[0],
                      alpha=0.15, color="#ff4444")
    ax1.set_ylabel("Equity ($)", color="#888888", fontsize=11)
    ax1.legend(loc="upper left", fontsize=9, facecolor="#1a1a1a", edgecolor="#333333", labelcolor="white")
    ax1.set_title("EQUITY CURVE", color="#888888", fontsize=10, loc="left")
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))

    # 2. Drawdown
    ax2 = axes[1]
    if "drawdown" in equity_df.columns:
        dd = equity_df["drawdown"]
    else:
        peak = equity_df["equity"].cummax()
        dd = (equity_df["equity"] - peak) / peak
    ax2.fill_between(equity_df.index, 0, dd, color="#ff4444", alpha=0.6)
    ax2.plot(equity_df.index, dd, color="#ff4444", linewidth=0.8)
    ax2.set_ylabel("Drawdown", color="#888888", fontsize=11)
    ax2.set_title("DRAWDOWN", color="#888888", fontsize=10, loc="left")
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.1%}"))

    # 3. Trade PnL distribution
    ax3 = axes[2]
    if not trades_df.empty and "pnl" in trades_df.columns:
        colors = ["#00ff88" if x > 0 else "#ff4444" for x in trades_df["pnl"]]
        ax3.bar(range(len(trades_df)), trades_df["pnl"], color=colors, width=0.8, alpha=0.8)
        ax3.axhline(y=0, color="#555555", linewidth=0.8)
        ax3.set_ylabel("PnL ($)", color="#888888", fontsize=11)
        ax3.set_xlabel("Trade #", color="#888888", fontsize=11)
    ax3.set_title("TRADE PnL", color="#888888", fontsize=10, loc="left")

    # 4. Cumulative PnL
    ax4 = axes[3]
    if not trades_df.empty and "pnl" in trades_df.columns:
        cum_pnl = trades_df["pnl"].cumsum()
        ax4.plot(range(len(cum_pnl)), cum_pnl, color="#ffaa00", linewidth=1.5)
        ax4.fill_between(range(len(cum_pnl)), 0, cum_pnl,
                          where=cum_pnl >= 0, alpha=0.15, color="#00ff88")
        ax4.fill_between(range(len(cum_pnl)), 0, cum_pnl,
                          where=cum_pnl < 0, alpha=0.15, color="#ff4444")
        ax4.axhline(y=0, color="#555555", linewidth=0.8)
        ax4.set_ylabel("Cumulative PnL ($)", color="#888888", fontsize=11)
        ax4.set_xlabel("Trade #", color="#888888", fontsize=11)
    ax4.set_title("CUMULATIVE PnL", color="#888888", fontsize=10, loc="left")

    plt.tight_layout()
    return fig


def plot_comparison(results: list[dict], title: str = "Strategy Comparison"):
    """Compare multiple backtest results side-by-side.

    Args:
        results: list of {"name": str, "equity_df": DataFrame, "metrics": dict}
    """
    sns.set_theme(style="dark")
    fig, axes = plt.subplots(1, 2, figsize=(18, 7))
    fig.suptitle(title, fontsize=16, fontweight="bold", color="white")
    fig.patch.set_facecolor("#0a0a0a")

    colors = ["#00ff88", "#ffaa00", "#ff4488", "#44aaff", "#aa44ff", "#ff8844"]

    for ax in axes:
        ax.set_facecolor("#0a0a0a")
        ax.tick_params(colors="#888888")
        ax.spines["bottom"].set_color("#333333")
        ax.spines["left"].set_color("#333333")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    # Normalized equity curves
    ax1 = axes[0]
    for i, r in enumerate(results):
        eq = r["equity_df"]["equity"]
        normalized = eq / eq.iloc[0] * 100
        ax1.plot(normalized.index, normalized, color=colors[i % len(colors)],
                 linewidth=1.5, label=r["name"])
    ax1.legend(facecolor="#1a1a1a", edgecolor="#333333", labelcolor="white")
    ax1.set_title("NORMALIZED EQUITY (base=100)", color="#888888", fontsize=10, loc="left")
    ax1.set_ylabel("Value", color="#888888")

    # Metrics comparison bar chart
    ax2 = axes[1]
    metric_keys = ["sharpe_ratio", "sortino_ratio", "max_drawdown", "win_rate", "profit_factor"]
    x = np.arange(len(metric_keys))
    width = 0.8 / len(results)
    for i, r in enumerate(results):
        values = [r["metrics"].get(k, 0) for k in metric_keys]
        ax2.bar(x + i * width, values, width, color=colors[i % len(colors)],
                label=r["name"], alpha=0.8)
    ax2.set_xticks(x + width * (len(results) - 1) / 2)
    ax2.set_xticklabels([k.replace("_", "\n") for k in metric_keys], color="#888888", fontsize=9)
    ax2.legend(facecolor="#1a1a1a", edgecolor="#333333", labelcolor="white")
    ax2.set_title("KEY METRICS", color="#888888", fontsize=10, loc="left")

    plt.tight_layout()
    return fig
