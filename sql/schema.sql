-- hype-backtesting: Trade and risk analytics schema (TimescaleDB/PostgreSQL)
--
-- Designed for time-series analytics on backtesting results and live trading.
-- Uses hypertables for efficient range queries on tick and bar data.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Raw candle data from Hyperliquid and equity feeds
CREATE TABLE candles (
    time        TIMESTAMPTZ NOT NULL,
    symbol      TEXT        NOT NULL,
    source      TEXT        NOT NULL DEFAULT 'hyperliquid',
    interval    TEXT        NOT NULL DEFAULT '1h',
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      DOUBLE PRECISION NOT NULL DEFAULT 0,
    funding     DOUBLE PRECISION,
    premium     DOUBLE PRECISION,
    UNIQUE (time, symbol, source, interval)
);

SELECT create_hypertable('candles', 'time');
CREATE INDEX idx_candles_symbol ON candles (symbol, time DESC);

-- Trade executions from backtests and live
CREATE TABLE trades (
    id              BIGSERIAL PRIMARY KEY,
    strategy        TEXT        NOT NULL,
    run_id          UUID        NOT NULL,
    symbol          TEXT        NOT NULL,
    side            TEXT        NOT NULL CHECK (side IN ('long', 'short')),
    entry_price     DOUBLE PRECISION NOT NULL,
    exit_price      DOUBLE PRECISION,
    size            DOUBLE PRECISION NOT NULL,
    notional        DOUBLE PRECISION NOT NULL,
    pnl             DOUBLE PRECISION,
    return_pct      DOUBLE PRECISION,
    commission      DOUBLE PRECISION NOT NULL DEFAULT 0,
    slippage        DOUBLE PRECISION NOT NULL DEFAULT 0,
    entry_time      TIMESTAMPTZ NOT NULL,
    exit_time       TIMESTAMPTZ,
    hold_bars       INT,
    stop_loss       DOUBLE PRECISION,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'stopped'))
);

CREATE INDEX idx_trades_strategy ON trades (strategy, entry_time DESC);
CREATE INDEX idx_trades_run ON trades (run_id);
CREATE INDEX idx_trades_symbol ON trades (symbol, entry_time DESC);

-- Equity curve snapshots (per bar)
CREATE TABLE equity_curve (
    time        TIMESTAMPTZ NOT NULL,
    run_id      UUID        NOT NULL,
    strategy    TEXT        NOT NULL,
    equity      DOUBLE PRECISION NOT NULL,
    drawdown    DOUBLE PRECISION NOT NULL DEFAULT 0,
    positions   INT         NOT NULL DEFAULT 0,
    long_exp    DOUBLE PRECISION DEFAULT 0,
    short_exp   DOUBLE PRECISION DEFAULT 0,
    UNIQUE (time, run_id)
);

SELECT create_hypertable('equity_curve', 'time');

-- Risk snapshots from the Rust risk engine
CREATE TABLE risk_snapshots (
    time              TIMESTAMPTZ NOT NULL,
    total_equity      DOUBLE PRECISION NOT NULL,
    net_exposure      DOUBLE PRECISION,
    gross_exposure    DOUBLE PRECISION,
    var_95            DOUBLE PRECISION,
    var_99            DOUBLE PRECISION,
    cvar_95           DOUBLE PRECISION,
    max_drawdown      DOUBLE PRECISION,
    current_drawdown  DOUBLE PRECISION,
    sharpe_realtime   DOUBLE PRECISION,
    correlation_risk  DOUBLE PRECISION,
    concentration_hhi DOUBLE PRECISION,
    margin_usage      DOUBLE PRECISION,
    positions         INT
);

SELECT create_hypertable('risk_snapshots', 'time');

-- Funding rate observations
CREATE TABLE funding_rates (
    time        TIMESTAMPTZ NOT NULL,
    symbol      TEXT        NOT NULL,
    rate        DOUBLE PRECISION NOT NULL,
    premium     DOUBLE PRECISION,
    annualized  DOUBLE PRECISION,
    UNIQUE (time, symbol)
);

SELECT create_hypertable('funding_rates', 'time');
CREATE INDEX idx_funding_symbol ON funding_rates (symbol, time DESC);

-- Backtest run metadata
CREATE TABLE backtest_runs (
    id              UUID PRIMARY KEY,
    strategy        TEXT        NOT NULL,
    params          JSONB       NOT NULL DEFAULT '{}',
    symbols         TEXT[]      NOT NULL,
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,
    initial_capital DOUBLE PRECISION NOT NULL,
    final_equity    DOUBLE PRECISION,
    total_return    DOUBLE PRECISION,
    sharpe          DOUBLE PRECISION,
    sortino         DOUBLE PRECISION,
    calmar          DOUBLE PRECISION,
    max_drawdown    DOUBLE PRECISION,
    win_rate        DOUBLE PRECISION,
    profit_factor   DOUBLE PRECISION,
    total_trades    INT,
    commission_bps  DOUBLE PRECISION,
    slippage_bps    DOUBLE PRECISION,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_runs_strategy ON backtest_runs (strategy, created_at DESC);
