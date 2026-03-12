"""Equities data client -- yfinance wrapper with caching."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

_CACHE_DIR = Path(".cache/equities")


class EquitiesClient:
    def __init__(self, cache_ttl_hours: float = 6.0):
        self.cache_ttl = cache_ttl_hours * 3600
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, ticker: str, interval: str, period: str) -> Path:
        h = hashlib.md5(f"{ticker}_{interval}_{period}".encode()).hexdigest()
        return _CACHE_DIR / f"{h}.parquet"

    def get_ohlcv(
        self,
        ticker: str,
        interval: str = "1d",
        period: str = "2y",
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV data for a ticker.

        Args:
            ticker: e.g. "AAPL", "SPY", "BTC-USD"
            interval: 1m, 5m, 15m, 1h, 1d, 1wk, 1mo
            period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, max
            start/end: date strings "YYYY-MM-DD" (overrides period)
        """
        cache_path = self._cache_key(ticker, interval, period)
        if cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < self.cache_ttl:
                return pd.read_parquet(cache_path)

        t = yf.Ticker(ticker)
        if start and end:
            df = t.history(interval=interval, start=start, end=end)
        else:
            df = t.history(interval=interval, period=period)

        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        df.index.name = "time"

        if not df.empty:
            df.to_parquet(cache_path)
        return df

    def get_multiple(
        self,
        tickers: list[str],
        interval: str = "1d",
        period: str = "2y",
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple tickers."""
        return {t: self.get_ohlcv(t, interval, period) for t in tickers}

    def get_fundamentals(self, ticker: str) -> dict:
        """Key fundamental ratios."""
        t = yf.Ticker(ticker)
        info = t.info
        keys = [
            "marketCap", "trailingPE", "forwardPE", "priceToBook",
            "dividendYield", "beta", "shortRatio", "earningsGrowth",
            "revenueGrowth", "profitMargins", "returnOnEquity",
        ]
        return {k: info.get(k) for k in keys}
