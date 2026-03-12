import useSWR from "swr";
import type { RiskMetrics, Position, EquityCurvePoint } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

const fetcher = (url: string) => fetch(url).then((r) => r.json());

/** Real-time risk metrics, polled at 500ms. */
export function useRiskMetrics() {
  return useSWR<RiskMetrics>(`${API_BASE}/api/risk`, fetcher, {
    refreshInterval: 500,
    revalidateOnFocus: false,
  });
}

/** Current positions, polled at 1s. */
export function usePositions() {
  return useSWR<Position[]>(`${API_BASE}/api/positions`, fetcher, {
    refreshInterval: 1000,
    revalidateOnFocus: false,
  });
}

/** Equity curve history for charting. */
export function useEquityCurve(period: string = "7d") {
  return useSWR<EquityCurvePoint[]>(
    `${API_BASE}/api/equity?period=${period}`,
    fetcher,
    { refreshInterval: 5000 }
  );
}
