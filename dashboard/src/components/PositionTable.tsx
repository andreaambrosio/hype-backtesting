import { usePositions } from "@/hooks/usePortfolio";
import { clsx } from "clsx";
import type { Position } from "@/types";

function PnlCell({ value }: { value: number }) {
  return (
    <td
      className={clsx(
        "px-4 py-2 text-right font-mono text-sm",
        value >= 0 ? "text-emerald-400" : "text-red-400"
      )}
    >
      {value >= 0 ? "+" : ""}
      {value.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}
    </td>
  );
}

/** Live position book with mark-to-market P&L. */
export default function PositionTable() {
  const { data: positions, error } = usePositions();

  if (error) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        <p className="text-zinc-600">Position feed disconnected</p>
      </div>
    );
  }

  const sorted = [...(positions || [])].sort(
    (a, b) => Math.abs(b.notional) - Math.abs(a.notional)
  );

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900">
      <div className="border-b border-zinc-800 px-4 py-3">
        <h2 className="text-lg font-semibold text-zinc-300">Positions</h2>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-zinc-800 text-xs uppercase tracking-wider text-zinc-500">
              <th className="px-4 py-2 text-left">Symbol</th>
              <th className="px-4 py-2 text-left">Side</th>
              <th className="px-4 py-2 text-right">Size</th>
              <th className="px-4 py-2 text-right">Entry</th>
              <th className="px-4 py-2 text-right">Mark</th>
              <th className="px-4 py-2 text-right">Notional</th>
              <th className="px-4 py-2 text-right">Unreal. P&L</th>
              <th className="px-4 py-2 text-right">Leverage</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td
                  colSpan={8}
                  className="px-4 py-8 text-center text-zinc-600"
                >
                  No open positions
                </td>
              </tr>
            ) : (
              sorted.map((pos: Position) => (
                <tr
                  key={pos.symbol}
                  className="border-b border-zinc-800/50 hover:bg-zinc-800/30"
                >
                  <td className="px-4 py-2 font-mono text-sm font-semibold text-white">
                    {pos.symbol}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={clsx(
                        "rounded px-2 py-0.5 text-xs font-medium",
                        pos.side === "long"
                          ? "bg-emerald-950 text-emerald-400"
                          : "bg-red-950 text-red-400"
                      )}
                    >
                      {pos.side.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-sm text-zinc-300">
                    {pos.size.toFixed(4)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-sm text-zinc-400">
                    ${pos.entryPrice.toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-sm text-zinc-300">
                    ${pos.markPrice.toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-sm text-zinc-300">
                    ${pos.notional.toLocaleString()}
                  </td>
                  <PnlCell value={pos.unrealizedPnl} />
                  <td className="px-4 py-2 text-right font-mono text-sm text-zinc-400">
                    {pos.leverage.toFixed(2)}x
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
