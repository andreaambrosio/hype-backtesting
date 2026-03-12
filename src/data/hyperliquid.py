"""Hyperliquid data client -- market data, HIP-3 vaults, funding rates, OHLCV."""

from __future__ import annotations

import time
import json
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
import requests

_CACHE_DIR = Path(".cache/hyperliquid")


class HyperliquidClient:
    BASE = "https://api.hyperliquid.xyz"

    def __init__(self, cache_ttl_hours: float = 6.0):
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"
        self.cache_ttl = cache_ttl_hours * 3600
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ── low-level ────────────────────────────────────────────────────────

    def _post(self, payload: dict) -> Any:
        cache_key = hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        cache_path = _CACHE_DIR / f"{cache_key}.json"

        if cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < self.cache_ttl:
                return json.loads(cache_path.read_text())

        resp = self.session.post(f"{self.BASE}/info", json=payload)
        resp.raise_for_status()
        data = resp.json()
        cache_path.write_text(json.dumps(data))
        return data

    # ── market data ──────────────────────────────────────────────────────

    def get_all_mids(self) -> dict[str, float]:
        """Current mid prices for all coins."""
        data = self._post({"type": "allMids"})
        return {k: float(v) for k, v in data.items()}

    def get_meta(self) -> dict:
        """Exchange metadata -- all listed perps with specs."""
        return self._post({"type": "meta"})

    def get_meta_and_asset_ctxs(self) -> tuple[dict, list[dict]]:
        """Meta + live context (funding, OI, mark price) for every asset."""
        data = self._post({"type": "metaAndAssetCtxs"})
        return data[0], data[1]

    def get_funding_history(self, coin: str, start_ms: int, end_ms: int | None = None) -> pd.DataFrame:
        """Historical funding rate snapshots (8h intervals)."""
        payload: dict[str, Any] = {"type": "fundingHistory", "coin": coin, "startTime": start_ms}
        if end_ms:
            payload["endTime"] = end_ms
        data = self._post(payload)
        df = pd.DataFrame(data)
        if df.empty:
            return df
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        df["fundingRate"] = df["fundingRate"].astype(float)
        df["premium"] = df["premium"].astype(float)
        return df.set_index("time").sort_index()

    def get_candles(
        self, coin: str, interval: str = "1h", start_ms: int | None = None, limit: int = 5000
    ) -> pd.DataFrame:
        """OHLCV candles. interval: 1m, 5m, 15m, 1h, 4h, 1d."""
        if start_ms is None:
            start_ms = int((time.time() - 90 * 86400) * 1000)
        payload = {
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval, "startTime": start_ms},
        }
        data = self._post(payload)
        df = pd.DataFrame(data)
        if df.empty:
            return df
        df["t"] = pd.to_datetime(df["t"], unit="ms")
        for col in ["o", "h", "l", "c", "v"]:
            df[col] = df[col].astype(float)
        df = df.rename(columns={"t": "time", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        return df.set_index("time").sort_index().head(limit)

    # ── HIP-3 vaults ────────────────────────────────────────────────────

    def get_vault_summaries(self) -> pd.DataFrame:
        """All HIP-3 vault summaries -- TVL, PnL, APR, leader address."""
        data = self._post({"type": "vaultSummaries"})
        rows = []
        for v in data:
            rows.append({
                "vault_address": v.get("vaultAddress", v.get("leader", "")),
                "name": v.get("name", ""),
                "tvl": float(v.get("tvl", 0)),
                "apr": float(v.get("apr", 0)),
                "pnl": float(v.get("allTimePnl", 0)),
                "depositors": int(v.get("followers", v.get("depositors", 0))),
                "leader": v.get("leader", ""),
            })
        return pd.DataFrame(rows)

    def get_vault_details(self, vault_address: str) -> dict:
        """Detailed HIP-3 vault info -- positions, share price, history."""
        return self._post({"type": "vaultDetails", "vaultAddress": vault_address})

    def get_vault_pnl_history(self, vault_address: str) -> pd.DataFrame:
        """Extract PnL time series from vault details for backtesting."""
        details = self.get_vault_details(vault_address)
        portfolio = details.get("portfolio", [])
        if not portfolio:
            return pd.DataFrame()
        rows = []
        for entry in portfolio:
            rows.append({
                "time": pd.to_datetime(entry["time"], unit="ms") if isinstance(entry.get("time"), (int, float)) else entry.get("time"),
                "account_value": float(entry.get("accountValue", 0)),
                "pnl": float(entry.get("pnl", 0)),
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.set_index("time").sort_index()
        return df

    # ── open interest & liquidations ─────────────────────────────────────

    def get_open_interest(self) -> pd.DataFrame:
        """Current OI for all coins."""
        _, ctxs = self.get_meta_and_asset_ctxs()
        meta = self.get_meta()
        coins = [a["name"] for a in meta["universe"]]
        rows = []
        for coin, ctx in zip(coins, ctxs):
            rows.append({
                "coin": coin,
                "funding_rate": float(ctx.get("funding", 0)),
                "open_interest": float(ctx.get("openInterest", 0)),
                "mark_price": float(ctx.get("markPx", 0)),
                "oracle_price": float(ctx.get("oraclePx", 0)),
                "premium": float(ctx.get("premium", 0)),
                "day_volume_ntl": float(ctx.get("dayNtlVlm", 0)),
            })
        return pd.DataFrame(rows).set_index("coin")

    # ── user data (for tracking specific wallets) ────────────────────────

    def get_user_state(self, address: str) -> dict:
        """Full account state -- positions, margin, PnL."""
        return self._post({"type": "clearinghouseState", "user": address})

    def get_user_fills(self, address: str, start_ms: int | None = None) -> pd.DataFrame:
        """Trade fills for a user."""
        payload: dict[str, Any] = {"type": "userFills", "user": address}
        if start_ms:
            payload["startTime"] = start_ms
        data = self._post(payload)
        df = pd.DataFrame(data)
        if df.empty:
            return df
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        for col in ["px", "sz", "fee"]:
            if col in df.columns:
                df[col] = df[col].astype(float)
        return df.set_index("time").sort_index()
