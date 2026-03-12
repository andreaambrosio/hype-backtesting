/** Types for the monitoring dashboard. */

export interface Position {
  symbol: string;
  side: "long" | "short";
  size: number;
  entryPrice: number;
  markPrice: number;
  notional: number;
  unrealizedPnl: number;
  leverage: number;
  timestamp: string;
}

export interface RiskMetrics {
  totalEquity: number;
  netExposure: number;
  grossExposure: number;
  longExposure: number;
  shortExposure: number;
  var95: number;
  var99: number;
  cvar95: number;
  maxDrawdown: number;
  currentDrawdown: number;
  sharpeRealtime: number;
  correlationRisk: number;
  concentrationHhi: number;
  marginUsage: number;
  positions: number;
  timestamp: string;
}

export interface EquityCurvePoint {
  timestamp: string;
  equity: number;
  drawdown: number;
  benchmark: number;
}

export interface TradeRecord {
  id: string;
  symbol: string;
  side: "long" | "short";
  entryPrice: number;
  exitPrice: number;
  size: number;
  pnl: number;
  returnPct: number;
  entryTime: string;
  exitTime: string;
  holdingPeriodHours: number;
  strategy: string;
}

export interface StrategyMetrics {
  name: string;
  totalReturn: number;
  sharpe: number;
  sortino: number;
  calmar: number;
  maxDrawdown: number;
  winRate: number;
  profitFactor: number;
  trades: number;
  isActive: boolean;
}

export interface MicrostructureSnapshot {
  symbol: string;
  midPrice: number;
  spreadBps: number;
  depthBid10Bps: number;
  depthAsk10Bps: number;
  tradeImbalance: number;
  vwap: number;
  fundingRate: number;
  fundingAnnualized: number;
  premium: number;
  timestamp: string;
}

export interface AlertEvent {
  id: string;
  severity: "info" | "warning" | "critical";
  type: string;
  message: string;
  timestamp: string;
  acknowledged: boolean;
}
