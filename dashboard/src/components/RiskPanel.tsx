import { useRiskMetrics } from "@/hooks/usePortfolio";
import { clsx } from "clsx";

function MetricCard({
  label,
  value,
  format = "number",
  threshold,
}: {
  label: string;
  value: number | undefined;
  format?: "number" | "currency" | "percent" | "ratio";
  threshold?: { warn: number; critical: number };
}) {
  if (value === undefined) return null;

  const formatted = (() => {
    switch (format) {
      case "currency":
        return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
      case "percent":
        return `${(value * 100).toFixed(2)}%`;
      case "ratio":
        return value.toFixed(2);
      default:
        return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
  })();

  const severity =
    threshold && Math.abs(value) >= threshold.critical
      ? "critical"
      : threshold && Math.abs(value) >= threshold.warn
        ? "warn"
        : "normal";

  return (
    <div
      className={clsx(
        "rounded-lg border p-4",
        severity === "critical" && "border-red-500 bg-red-950/30",
        severity === "warn" && "border-amber-500 bg-amber-950/20",
        severity === "normal" && "border-zinc-800 bg-zinc-900"
      )}
    >
      <p className="text-xs uppercase tracking-wider text-zinc-500">{label}</p>
      <p
        className={clsx(
          "mt-1 text-2xl font-mono font-bold",
          severity === "critical" && "text-red-400",
          severity === "warn" && "text-amber-400",
          severity === "normal" && "text-white"
        )}
      >
        {formatted}
      </p>
    </div>
  );
}

/** Real-time portfolio risk metrics panel. */
export default function RiskPanel() {
  const { data: metrics, error } = useRiskMetrics();

  if (error) {
    return (
      <div className="rounded-lg border border-red-800 bg-red-950/20 p-6">
        <p className="text-red-400">Risk engine disconnected</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-zinc-300">Risk Overview</h2>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard
          label="Total Equity"
          value={metrics?.totalEquity}
          format="currency"
        />
        <MetricCard
          label="Net Exposure"
          value={metrics?.netExposure}
          format="currency"
        />
        <MetricCard
          label="Gross Exposure"
          value={metrics?.grossExposure}
          format="currency"
        />
        <MetricCard
          label="Positions"
          value={metrics?.positions}
        />
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard
          label="VaR (95%)"
          value={metrics?.var95}
          format="currency"
          threshold={{ warn: 30000, critical: 50000 }}
        />
        <MetricCard
          label="CVaR (95%)"
          value={metrics?.cvar95}
          format="currency"
          threshold={{ warn: 40000, critical: 60000 }}
        />
        <MetricCard
          label="Current Drawdown"
          value={metrics?.currentDrawdown}
          format="percent"
          threshold={{ warn: 0.08, critical: 0.15 }}
        />
        <MetricCard
          label="Max Drawdown"
          value={metrics?.maxDrawdown}
          format="percent"
          threshold={{ warn: 0.10, critical: 0.20 }}
        />
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard
          label="Sharpe (Realtime)"
          value={metrics?.sharpeRealtime}
          format="ratio"
        />
        <MetricCard
          label="Correlation Risk"
          value={metrics?.correlationRisk}
          format="ratio"
          threshold={{ warn: 0.7, critical: 0.9 }}
        />
        <MetricCard
          label="Concentration (HHI)"
          value={metrics?.concentrationHhi}
          format="ratio"
          threshold={{ warn: 0.4, critical: 0.6 }}
        />
        <MetricCard
          label="Margin Usage"
          value={metrics?.marginUsage}
          format="ratio"
          threshold={{ warn: 2.0, critical: 3.0 }}
        />
      </div>
    </div>
  );
}
