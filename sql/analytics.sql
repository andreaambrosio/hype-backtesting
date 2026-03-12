-- Analytical queries for backtest performance analysis.
-- Run against the populated schema after backtesting.

-- Strategy leaderboard: ranked by risk-adjusted return
SELECT
    br.strategy,
    br.total_return,
    br.sharpe,
    br.sortino,
    br.calmar,
    br.max_drawdown,
    br.win_rate,
    br.profit_factor,
    br.total_trades,
    br.final_equity,
    br.created_at
FROM backtest_runs br
ORDER BY br.sharpe DESC NULLS LAST;


-- Rolling 24h Sharpe ratio per strategy
WITH hourly_returns AS (
    SELECT
        run_id,
        strategy,
        time,
        (equity - LAG(equity) OVER (PARTITION BY run_id ORDER BY time))
            / NULLIF(LAG(equity) OVER (PARTITION BY run_id ORDER BY time), 0) AS ret
    FROM equity_curve
)
SELECT
    strategy,
    time_bucket('24 hours', time) AS bucket,
    AVG(ret) / NULLIF(STDDEV(ret), 0) * SQRT(24) AS rolling_sharpe,
    COUNT(*) AS observations
FROM hourly_returns
WHERE ret IS NOT NULL
GROUP BY strategy, bucket
ORDER BY strategy, bucket;


-- Win rate by symbol and strategy
SELECT
    strategy,
    symbol,
    COUNT(*) AS trades,
    COUNT(*) FILTER (WHERE pnl > 0) AS winners,
    COUNT(*) FILTER (WHERE pnl <= 0) AS losers,
    ROUND(100.0 * COUNT(*) FILTER (WHERE pnl > 0) / NULLIF(COUNT(*), 0), 1) AS win_rate_pct,
    ROUND(AVG(pnl)::NUMERIC, 2) AS avg_pnl,
    ROUND(AVG(pnl) FILTER (WHERE pnl > 0)::NUMERIC, 2) AS avg_winner,
    ROUND(AVG(pnl) FILTER (WHERE pnl <= 0)::NUMERIC, 2) AS avg_loser,
    ROUND(AVG(hold_bars)::NUMERIC, 1) AS avg_hold_bars
FROM trades
WHERE status = 'closed'
GROUP BY strategy, symbol
ORDER BY strategy, win_rate_pct DESC;


-- Drawdown analysis: top 5 drawdown events per strategy
WITH dd_events AS (
    SELECT
        strategy,
        run_id,
        time,
        drawdown,
        LAG(drawdown) OVER (PARTITION BY run_id ORDER BY time) AS prev_dd
    FROM equity_curve
),
dd_starts AS (
    SELECT *,
        CASE WHEN drawdown > 0 AND (prev_dd IS NULL OR prev_dd = 0) THEN 1 ELSE 0 END AS is_start
    FROM dd_events
),
dd_groups AS (
    SELECT *,
        SUM(is_start) OVER (PARTITION BY run_id ORDER BY time) AS dd_group
    FROM dd_starts
    WHERE drawdown > 0
)
SELECT
    strategy,
    dd_group,
    MIN(time) AS start_time,
    MAX(time) AS end_time,
    MAX(drawdown) AS peak_drawdown,
    EXTRACT(EPOCH FROM MAX(time) - MIN(time)) / 3600 AS duration_hours
FROM dd_groups
GROUP BY strategy, run_id, dd_group
ORDER BY strategy, peak_drawdown DESC
LIMIT 20;


-- Funding rate regime analysis: average funding by time-of-day
SELECT
    symbol,
    EXTRACT(HOUR FROM time) AS hour_utc,
    AVG(rate) AS avg_rate,
    STDDEV(rate) AS std_rate,
    AVG(rate) * 3 * 365.25 AS annualized,
    COUNT(*) AS obs
FROM funding_rates
GROUP BY symbol, hour_utc
ORDER BY symbol, hour_utc;


-- Cross-asset correlation matrix (daily returns)
WITH daily_returns AS (
    SELECT
        time_bucket('1 day', time) AS day,
        symbol,
        (LAST(close, time) - FIRST(open, time)) / NULLIF(FIRST(open, time), 0) AS ret
    FROM candles
    WHERE source = 'hyperliquid'
    GROUP BY day, symbol
)
SELECT
    a.symbol AS sym_a,
    b.symbol AS sym_b,
    CORR(a.ret, b.ret) AS correlation,
    COUNT(*) AS days
FROM daily_returns a
JOIN daily_returns b ON a.day = b.day AND a.symbol < b.symbol
GROUP BY a.symbol, b.symbol
HAVING COUNT(*) >= 30
ORDER BY ABS(CORR(a.ret, b.ret)) DESC;


-- Optimal rebalance frequency: Sharpe by hold period bucket
SELECT
    strategy,
    CASE
        WHEN hold_bars <= 6 THEN '0-6h'
        WHEN hold_bars <= 24 THEN '6-24h'
        WHEN hold_bars <= 72 THEN '1-3d'
        ELSE '3d+'
    END AS hold_bucket,
    COUNT(*) AS trades,
    ROUND(AVG(return_pct)::NUMERIC, 4) AS avg_return,
    ROUND(AVG(return_pct)::NUMERIC / NULLIF(STDDEV(return_pct)::NUMERIC, 0), 4) AS trade_sharpe,
    ROUND(SUM(pnl)::NUMERIC, 2) AS total_pnl
FROM trades
WHERE status = 'closed'
GROUP BY strategy, hold_bucket
ORDER BY strategy, hold_bucket;
