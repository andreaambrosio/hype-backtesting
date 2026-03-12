import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from "recharts";
import { useEquityCurve } from "@/hooks/usePortfolio";
import { format, parseISO } from "date-fns";
import type { EquityCurvePoint } from "@/types";

function formatCurrency(value: number): string {
  return `$${(value / 1000).toFixed(1)}k`;
}

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: EquityCurvePoint }>;
}) {
  if (!active || !payload?.length) return null;

  const point = payload[0].payload;

  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900 p-3 shadow-xl">
      <p className="text-xs text-zinc-500">
        {format(parseISO(point.timestamp), "MMM d, HH:mm")}
      </p>
      <p className="text-sm font-mono text-white">
        Equity: ${point.equity.toLocaleString()}
      </p>
      <p className="text-sm font-mono text-zinc-400">
        Benchmark: ${point.benchmark.toLocaleString()}
      </p>
      <p
        className={`text-sm font-mono ${
          point.drawdown > 0.05 ? "text-red-400" : "text-zinc-500"
        }`}
      >
        DD: {(point.drawdown * 100).toFixed(2)}%
      </p>
    </div>
  );
}

interface EquityChartProps {
  period?: string;
  height?: number;
}

/** Equity curve with drawdown overlay and benchmark comparison. */
export default function EquityChart({
  period = "7d",
  height = 400,
}: EquityChartProps) {
  const { data, error, isLoading } = useEquityCurve(period);

  if (isLoading) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900"
        style={{ height }}
      >
        <p className="text-zinc-600">Loading equity curve...</p>
      </div>
    );
  }

  if (error || !data?.length) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900"
        style={{ height }}
      >
        <p className="text-zinc-600">No equity data available</p>
      </div>
    );
  }

  const initial = data[0].equity;

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-300">Equity Curve</h2>
        <div className="flex gap-4 text-xs text-zinc-500">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
            Portfolio
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-zinc-600" />
            Benchmark
          </span>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
          <XAxis
            dataKey="timestamp"
            tickFormatter={(v: string) => format(parseISO(v), "MMM d")}
            stroke="#52525b"
            fontSize={11}
          />
          <YAxis
            yAxisId="equity"
            tickFormatter={formatCurrency}
            stroke="#52525b"
            fontSize={11}
          />
          <YAxis
            yAxisId="dd"
            orientation="right"
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            stroke="#52525b"
            fontSize={11}
            domain={[0, "auto"]}
          />
          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine
            yAxisId="equity"
            y={initial}
            stroke="#52525b"
            strokeDasharray="5 5"
          />
          <Area
            yAxisId="dd"
            type="monotone"
            dataKey="drawdown"
            fill="#dc2626"
            fillOpacity={0.15}
            stroke="none"
          />
          <Line
            yAxisId="equity"
            type="monotone"
            dataKey="benchmark"
            stroke="#52525b"
            strokeWidth={1}
            dot={false}
          />
          <Line
            yAxisId="equity"
            type="monotone"
            dataKey="equity"
            stroke="#10b981"
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
