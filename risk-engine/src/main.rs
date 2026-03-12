//! Real-time portfolio risk engine.
//!
//! Computes VaR, exposure limits, and concentration metrics on every position
//! update. Reads positions from Redis, publishes risk snapshots back.
//! Dashboard polls at 100ms for live display.

use chrono::{DateTime, Utc};
use nalgebra::{DMatrix, DVector};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Single position in the portfolio.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Position {
    pub symbol: String,
    pub side: Side,
    pub size: f64,
    pub entry_price: f64,
    pub mark_price: f64,
    pub notional: f64,
    pub unrealized_pnl: f64,
    pub leverage: f64,
    pub timestamp: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum Side {
    Long,
    Short,
}

/// Portfolio-level risk metrics.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskMetrics {
    pub total_equity: f64,
    pub net_exposure: f64,
    pub gross_exposure: f64,
    pub long_exposure: f64,
    pub short_exposure: f64,
    pub var_95: f64,
    pub var_99: f64,
    pub cvar_95: f64,
    pub max_drawdown: f64,
    pub current_drawdown: f64,
    pub sharpe_realtime: f64,
    pub correlation_risk: f64,
    pub concentration_hhi: f64,
    pub margin_usage: f64,
    pub positions: usize,
    pub timestamp: DateTime<Utc>,
}

/// Covariance-based risk engine.
pub struct RiskEngine {
    positions: HashMap<String, Position>,
    returns_history: HashMap<String, Vec<f64>>,
    equity_history: Vec<f64>,
    peak_equity: f64,
    initial_capital: f64,
    lookback: usize,
    var_confidence_95: f64,
    var_confidence_99: f64,
}

impl RiskEngine {
    pub fn new(initial_capital: f64, lookback: usize) -> Self {
        Self {
            positions: HashMap::new(),
            returns_history: HashMap::new(),
            equity_history: vec![initial_capital],
            peak_equity: initial_capital,
            initial_capital,
            lookback,
            var_confidence_95: 1.645,
            var_confidence_99: 2.326,
        }
    }

    /// Update a position -- called on every fill or mark price change.
    pub fn update_position(&mut self, pos: Position) {
        self.positions.insert(pos.symbol.clone(), pos);
    }

    /// Remove a closed position.
    pub fn remove_position(&mut self, symbol: &str) {
        self.positions.remove(symbol);
    }

    /// Push a new return observation for a symbol.
    pub fn push_return(&mut self, symbol: &str, ret: f64) {
        let history = self.returns_history
            .entry(symbol.to_string())
            .or_insert_with(Vec::new);
        history.push(ret);
        if history.len() > self.lookback {
            history.remove(0);
        }
    }

    /// Compute the full covariance matrix from return histories.
    fn covariance_matrix(&self, symbols: &[String]) -> Option<DMatrix<f64>> {
        let n = symbols.len();
        if n == 0 {
            return None;
        }

        let min_obs = symbols.iter()
            .filter_map(|s| self.returns_history.get(s))
            .map(|h| h.len())
            .min()
            .unwrap_or(0);

        if min_obs < 20 {
            return None;
        }

        let mut cov = DMatrix::zeros(n, n);
        for i in 0..n {
            for j in 0..=i {
                let ri = self.returns_history.get(&symbols[i])?;
                let rj = self.returns_history.get(&symbols[j])?;

                let len = min_obs.min(ri.len()).min(rj.len());
                let ri_slice = &ri[ri.len() - len..];
                let rj_slice = &rj[rj.len() - len..];

                let mean_i: f64 = ri_slice.iter().sum::<f64>() / len as f64;
                let mean_j: f64 = rj_slice.iter().sum::<f64>() / len as f64;

                let cov_ij: f64 = ri_slice.iter().zip(rj_slice.iter())
                    .map(|(a, b)| (a - mean_i) * (b - mean_j))
                    .sum::<f64>() / (len - 1) as f64;

                cov[(i, j)] = cov_ij;
                cov[(j, i)] = cov_ij;
            }
        }

        Some(cov)
    }

    /// Parametric portfolio VaR using covariance matrix.
    fn parametric_var(&self, confidence: f64) -> f64 {
        let symbols: Vec<String> = self.positions.keys().cloned().collect();
        if symbols.is_empty() {
            return 0.0;
        }

        let weights: Vec<f64> = symbols.iter()
            .map(|s| {
                let pos = &self.positions[s];
                let sign = if pos.side == Side::Long { 1.0 } else { -1.0 };
                sign * pos.notional
            })
            .collect();

        let total_notional: f64 = weights.iter().map(|w| w.abs()).sum();
        if total_notional == 0.0 {
            return 0.0;
        }

        match self.covariance_matrix(&symbols) {
            Some(cov) => {
                let w = DVector::from_vec(weights);
                let portfolio_var = (w.transpose() * &cov * &w)[(0, 0)];
                let portfolio_std = portfolio_var.max(0.0).sqrt();
                confidence * portfolio_std
            }
            None => {
                // Fallback: sum of individual VaRs (conservative)
                symbols.iter()
                    .filter_map(|s| {
                        let history = self.returns_history.get(s)?;
                        if history.len() < 20 { return None; }
                        let mean: f64 = history.iter().sum::<f64>() / history.len() as f64;
                        let var: f64 = history.iter()
                            .map(|r| (r - mean).powi(2))
                            .sum::<f64>() / (history.len() - 1) as f64;
                        let std = var.sqrt();
                        let pos = &self.positions[s];
                        Some(confidence * std * pos.notional)
                    })
                    .sum()
            }
        }
    }

    /// Conditional VaR (Expected Shortfall) -- average loss beyond VaR.
    fn conditional_var(&self, confidence_z: f64) -> f64 {
        // For normal distribution: CVaR = σ * φ(z) / (1 - α)
        // Simplified: use 1.25x VaR as approximation
        self.parametric_var(confidence_z) * 1.25
    }

    /// Herfindahl-Hirschman Index for concentration risk.
    fn concentration_hhi(&self) -> f64 {
        let total: f64 = self.positions.values()
            .map(|p| p.notional)
            .sum();

        if total == 0.0 {
            return 0.0;
        }

        self.positions.values()
            .map(|p| (p.notional / total).powi(2))
            .sum()
    }

    /// Average pairwise correlation across portfolio.
    fn avg_correlation(&self) -> f64 {
        let symbols: Vec<String> = self.positions.keys().cloned().collect();
        let n = symbols.len();
        if n < 2 {
            return 0.0;
        }

        match self.covariance_matrix(&symbols) {
            Some(cov) => {
                let mut total_corr = 0.0;
                let mut count = 0;
                for i in 0..n {
                    for j in (i + 1)..n {
                        let denom = (cov[(i, i)] * cov[(j, j)]).sqrt();
                        if denom > 0.0 {
                            total_corr += cov[(i, j)] / denom;
                            count += 1;
                        }
                    }
                }
                if count > 0 { total_corr / count as f64 } else { 0.0 }
            }
            None => 0.0,
        }
    }

    /// Compute all risk metrics for the current portfolio state.
    pub fn compute_metrics(&mut self) -> RiskMetrics {
        let mut long_exp = 0.0;
        let mut short_exp = 0.0;
        let mut total_pnl = 0.0;

        for pos in self.positions.values() {
            match pos.side {
                Side::Long => long_exp += pos.notional,
                Side::Short => short_exp += pos.notional,
            }
            total_pnl += pos.unrealized_pnl;
        }

        let equity = self.initial_capital + total_pnl;
        self.equity_history.push(equity);
        if equity > self.peak_equity {
            self.peak_equity = equity;
        }

        let current_dd = if self.peak_equity > 0.0 {
            (self.peak_equity - equity) / self.peak_equity
        } else {
            0.0
        };

        let max_dd = self.equity_history.iter()
            .scan(f64::MIN, |peak, &eq| {
                *peak = peak.max(eq);
                Some((*peak - eq) / *peak)
            })
            .fold(0.0_f64, |a, b| a.max(b));

        // Real-time Sharpe from equity curve
        let sharpe = if self.equity_history.len() > 20 {
            let returns: Vec<f64> = self.equity_history.windows(2)
                .map(|w| (w[1] - w[0]) / w[0])
                .collect();
            let mean: f64 = returns.iter().sum::<f64>() / returns.len() as f64;
            let var: f64 = returns.iter()
                .map(|r| (r - mean).powi(2))
                .sum::<f64>() / (returns.len() - 1) as f64;
            let std = var.sqrt();
            if std > 0.0 { mean / std * (252.0_f64).sqrt() } else { 0.0 }
        } else {
            0.0
        };

        let gross = long_exp + short_exp;
        let margin_usage = if equity > 0.0 { gross / equity } else { 0.0 };

        RiskMetrics {
            total_equity: equity,
            net_exposure: long_exp - short_exp,
            gross_exposure: gross,
            long_exposure: long_exp,
            short_exposure: short_exp,
            var_95: self.parametric_var(self.var_confidence_95),
            var_99: self.parametric_var(self.var_confidence_99),
            cvar_95: self.conditional_var(self.var_confidence_95),
            max_drawdown: max_dd,
            current_drawdown: current_dd,
            sharpe_realtime: sharpe,
            correlation_risk: self.avg_correlation(),
            concentration_hhi: self.concentration_hhi(),
            margin_usage,
            positions: self.positions.len(),
            timestamp: Utc::now(),
        }
    }
}

/// Breach types for limit monitoring.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum LimitBreach {
    MaxDrawdown { current: f64, limit: f64 },
    VarExceeded { var: f64, limit: f64 },
    ConcentrationExceeded { hhi: f64, limit: f64 },
    GrossExposureExceeded { gross: f64, limit: f64 },
    MarginExceeded { usage: f64, limit: f64 },
}

/// Risk limits configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskLimits {
    pub max_drawdown: f64,
    pub max_var_95: f64,
    pub max_concentration_hhi: f64,
    pub max_gross_exposure: f64,
    pub max_margin_usage: f64,
}

impl Default for RiskLimits {
    fn default() -> Self {
        Self {
            max_drawdown: 0.15,
            max_var_95: 50_000.0,
            max_concentration_hhi: 0.5,
            max_gross_exposure: 500_000.0,
            max_margin_usage: 3.0,
        }
    }
}

impl RiskLimits {
    /// Check all limits against current metrics, return any breaches.
    pub fn check(&self, metrics: &RiskMetrics) -> Vec<LimitBreach> {
        let mut breaches = Vec::new();

        if metrics.current_drawdown > self.max_drawdown {
            breaches.push(LimitBreach::MaxDrawdown {
                current: metrics.current_drawdown,
                limit: self.max_drawdown,
            });
        }
        if metrics.var_95 > self.max_var_95 {
            breaches.push(LimitBreach::VarExceeded {
                var: metrics.var_95,
                limit: self.max_var_95,
            });
        }
        if metrics.concentration_hhi > self.max_concentration_hhi {
            breaches.push(LimitBreach::ConcentrationExceeded {
                hhi: metrics.concentration_hhi,
                limit: self.max_concentration_hhi,
            });
        }
        if metrics.gross_exposure > self.max_gross_exposure {
            breaches.push(LimitBreach::GrossExposureExceeded {
                gross: metrics.gross_exposure,
                limit: self.max_gross_exposure,
            });
        }
        if metrics.margin_usage > self.max_margin_usage {
            breaches.push(LimitBreach::MarginExceeded {
                usage: metrics.margin_usage,
                limit: self.max_margin_usage,
            });
        }

        breaches
    }
}

#[tokio::main]
async fn main() {
    tracing_subscriber::init();

    let mut engine = RiskEngine::new(100_000.0, 500);
    let limits = RiskLimits::default();

    tracing::info!("risk engine started -- polling position updates");

    // In production: connect to Redis stream for position updates.
    // For now, demonstrate the computation pipeline.
    let demo_position = Position {
        symbol: "BTC".to_string(),
        side: Side::Long,
        size: 1.5,
        entry_price: 84_000.0,
        mark_price: 84_250.0,
        notional: 126_375.0,
        unrealized_pnl: 375.0,
        leverage: 1.26,
        timestamp: Utc::now(),
    };

    engine.update_position(demo_position);

    // Seed some return history for VaR computation
    for i in 0..100 {
        let ret = 0.001 * ((i as f64 * 0.1).sin()) + 0.0001;
        engine.push_return("BTC", ret);
    }

    let metrics = engine.compute_metrics();
    let breaches = limits.check(&metrics);

    tracing::info!(
        equity = metrics.total_equity,
        var_95 = metrics.var_95,
        drawdown = metrics.current_drawdown,
        positions = metrics.positions,
        "risk snapshot"
    );

    if !breaches.is_empty() {
        tracing::warn!(count = breaches.len(), "LIMIT BREACHES DETECTED");
        for b in &breaches {
            tracing::warn!(?b, "breach");
        }
    }

    println!("{}", serde_json::to_string_pretty(&metrics).unwrap());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty_portfolio() {
        let mut engine = RiskEngine::new(100_000.0, 100);
        let metrics = engine.compute_metrics();
        assert_eq!(metrics.positions, 0);
        assert_eq!(metrics.var_95, 0.0);
        assert_eq!(metrics.gross_exposure, 0.0);
    }

    #[test]
    fn test_single_position_exposure() {
        let mut engine = RiskEngine::new(100_000.0, 100);
        engine.update_position(Position {
            symbol: "ETH".into(),
            side: Side::Long,
            size: 10.0,
            entry_price: 3200.0,
            mark_price: 3250.0,
            notional: 32_500.0,
            unrealized_pnl: 500.0,
            leverage: 0.325,
            timestamp: Utc::now(),
        });
        let metrics = engine.compute_metrics();
        assert_eq!(metrics.positions, 1);
        assert_eq!(metrics.long_exposure, 32_500.0);
        assert_eq!(metrics.short_exposure, 0.0);
    }

    #[test]
    fn test_limit_breach_drawdown() {
        let limits = RiskLimits { max_drawdown: 0.05, ..Default::default() };
        let metrics = RiskMetrics {
            total_equity: 90_000.0,
            current_drawdown: 0.10,
            max_drawdown: 0.10,
            var_95: 0.0, var_99: 0.0, cvar_95: 0.0,
            net_exposure: 0.0, gross_exposure: 0.0,
            long_exposure: 0.0, short_exposure: 0.0,
            sharpe_realtime: 0.0, correlation_risk: 0.0,
            concentration_hhi: 0.0, margin_usage: 0.0,
            positions: 0, timestamp: Utc::now(),
        };
        let breaches = limits.check(&metrics);
        assert_eq!(breaches.len(), 1);
    }

    #[test]
    fn test_concentration_hhi() {
        let mut engine = RiskEngine::new(100_000.0, 100);
        engine.update_position(Position {
            symbol: "BTC".into(), side: Side::Long,
            size: 1.0, entry_price: 80_000.0, mark_price: 80_000.0,
            notional: 80_000.0, unrealized_pnl: 0.0, leverage: 0.8,
            timestamp: Utc::now(),
        });
        // Single position → HHI = 1.0
        assert!((engine.concentration_hhi() - 1.0).abs() < 1e-10);

        engine.update_position(Position {
            symbol: "ETH".into(), side: Side::Long,
            size: 25.0, entry_price: 3200.0, mark_price: 3200.0,
            notional: 80_000.0, unrealized_pnl: 0.0, leverage: 0.8,
            timestamp: Utc::now(),
        });
        // Two equal positions → HHI = 0.5
        assert!((engine.concentration_hhi() - 0.5).abs() < 1e-10);
    }
}
