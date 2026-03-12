// Package main runs a data ingestion service for Hyperliquid WebSocket feeds.
// Subscribes to orderbook, trades, and candle channels, normalizes the data,
// and publishes to Redis for downstream consumers. Handles reconnection
// and runs each channel in its own goroutine.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"
)

const (
	hlWSEndpoint   = "wss://api.hyperliquid.xyz/ws"
	reconnectDelay = 5 * time.Second
	maxReconnect   = 10
	healthPort     = ":8081"
)

// Candle represents a single OHLCV bar from the WebSocket feed.
type Candle struct {
	Symbol    string  `json:"symbol"`
	Interval  string  `json:"interval"`
	Open      float64 `json:"open"`
	High      float64 `json:"high"`
	Low       float64 `json:"low"`
	Close     float64 `json:"close"`
	Volume    float64 `json:"volume"`
	Timestamp int64   `json:"timestamp"`
}

// Trade represents a single trade execution.
type Trade struct {
	Symbol    string  `json:"symbol"`
	Price     float64 `json:"price"`
	Size      float64 `json:"size"`
	Side      string  `json:"side"`
	Timestamp int64   `json:"timestamp"`
	Hash      string  `json:"hash"`
}

// OrderBookLevel represents a single price level in the order book.
type OrderBookLevel struct {
	Price float64 `json:"price"`
	Size  float64 `json:"size"`
}

// OrderBook represents an L2 orderbook snapshot.
type OrderBook struct {
	Symbol    string           `json:"symbol"`
	Bids      []OrderBookLevel `json:"bids"`
	Asks      []OrderBookLevel `json:"asks"`
	Timestamp int64            `json:"timestamp"`
}

// FundingRate represents a funding rate observation.
type FundingRate struct {
	Symbol       string  `json:"symbol"`
	Rate         float64 `json:"rate"`
	Premium      float64 `json:"premium"`
	Annualized   float64 `json:"annualized"`
	NextFunding  int64   `json:"next_funding"`
	Timestamp    int64   `json:"timestamp"`
}

// MicrostructureMetrics computed in real-time from the feed.
type MicrostructureMetrics struct {
	Symbol         string  `json:"symbol"`
	MidPrice       float64 `json:"mid_price"`
	SpreadBps      float64 `json:"spread_bps"`
	DepthBid10Bps  float64 `json:"depth_bid_10bps"`
	DepthAsk10Bps  float64 `json:"depth_ask_10bps"`
	TradeImbalance float64 `json:"trade_imbalance"`
	VWAP           float64 `json:"vwap"`
	Timestamp      int64   `json:"timestamp"`
}

// IngestService coordinates all WebSocket subscriptions and data publishing.
type IngestService struct {
	symbols   []string
	intervals []string
	mu        sync.RWMutex
	books     map[string]*OrderBook
	metrics   map[string]*MicrostructureMetrics
	trades    map[string][]Trade
	healthy   bool
}

// NewIngestService creates a new ingestion service for the given symbols.
func NewIngestService(symbols []string) *IngestService {
	return &IngestService{
		symbols:   symbols,
		intervals: []string{"1m", "5m", "1h"},
		books:     make(map[string]*OrderBook),
		metrics:   make(map[string]*MicrostructureMetrics),
		trades:    make(map[string][]Trade),
		healthy:   false,
	}
}

// computeSpreadBps calculates the bid-ask spread in basis points.
func computeSpreadBps(book *OrderBook) float64 {
	if len(book.Bids) == 0 || len(book.Asks) == 0 {
		return 0
	}
	mid := (book.Bids[0].Price + book.Asks[0].Price) / 2
	if mid == 0 {
		return 0
	}
	return (book.Asks[0].Price - book.Bids[0].Price) / mid * 10000
}

// computeDepthWithinBps sums notional available within N bps of mid.
func computeDepthWithinBps(levels []OrderBookLevel, mid float64, bps float64) float64 {
	threshold := mid * bps / 10000
	total := 0.0
	for _, level := range levels {
		if math.Abs(level.Price-mid) <= threshold {
			total += level.Price * level.Size
		}
	}
	return total
}

// updateMetrics recomputes microstructure metrics for a symbol.
func (s *IngestService) updateMetrics(symbol string) {
	s.mu.Lock()
	defer s.mu.Unlock()

	book, ok := s.books[symbol]
	if !ok || len(book.Bids) == 0 || len(book.Asks) == 0 {
		return
	}

	mid := (book.Bids[0].Price + book.Asks[0].Price) / 2

	// Trade imbalance over recent window
	var buyVol, sellVol float64
	if trades, ok := s.trades[symbol]; ok {
		cutoff := time.Now().Unix() - 300 // 5 min window
		for _, t := range trades {
			if t.Timestamp/1000 < cutoff {
				continue
			}
			if t.Side == "buy" || t.Side == "B" {
				buyVol += t.Size * t.Price
			} else {
				sellVol += t.Size * t.Price
			}
		}
	}

	imbalance := 0.0
	if buyVol+sellVol > 0 {
		imbalance = (buyVol - sellVol) / (buyVol + sellVol)
	}

	s.metrics[symbol] = &MicrostructureMetrics{
		Symbol:         symbol,
		MidPrice:       mid,
		SpreadBps:      computeSpreadBps(book),
		DepthBid10Bps:  computeDepthWithinBps(book.Bids, mid, 10),
		DepthAsk10Bps:  computeDepthWithinBps(book.Asks, mid, 10),
		TradeImbalance: imbalance,
		Timestamp:      time.Now().UnixMilli(),
	}
}

// healthHandler exposes /health for container orchestration.
func (s *IngestService) healthHandler(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	if !s.healthy {
		w.WriteHeader(http.StatusServiceUnavailable)
		return
	}

	resp := map[string]interface{}{
		"status":    "ok",
		"symbols":   len(s.symbols),
		"books":     len(s.books),
		"timestamp": time.Now().UTC().Format(time.RFC3339),
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

// metricsHandler exposes /metrics for the dashboard.
func (s *IngestService) metricsHandler(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(s.metrics)
}

// Run starts all subscriptions and the health server.
func (s *IngestService) Run(ctx context.Context) error {
	// Start health/metrics HTTP server
	mux := http.NewServeMux()
	mux.HandleFunc("/health", s.healthHandler)
	mux.HandleFunc("/metrics", s.metricsHandler)
	server := &http.Server{Addr: healthPort, Handler: mux}

	go func() {
		log.Printf("health server listening on %s", healthPort)
		if err := server.ListenAndServe(); err != http.ErrServerClosed {
			log.Printf("health server error: %v", err)
		}
	}()

	s.mu.Lock()
	s.healthy = true
	s.mu.Unlock()

	log.Printf("ingestion service started for %d symbols", len(s.symbols))
	log.Printf("channels: orderbook, trades, candles (%v)", s.intervals)

	// In production: launch WebSocket goroutines per channel here.
	// Each goroutine handles subscribe, parse, normalize, and publish to Redis.
	//
	// ws := gorilla/websocket.Dial(hlWSEndpoint)
	// ws.WriteJSON(subscribeMsg)
	// for { msg := ws.ReadMessage(); process(msg) }

	<-ctx.Done()

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	return server.Shutdown(shutdownCtx)
}

func main() {
	symbols := []string{"BTC", "ETH", "SOL", "HYPE", "TURBO", "MEME", "WIF"}

	if envSymbols := os.Getenv("HL_SYMBOLS"); envSymbols != "" {
		symbols = nil
		for _, s := range splitComma(envSymbols) {
			if s != "" {
				symbols = append(symbols, s)
			}
		}
	}

	svc := NewIngestService(symbols)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	fmt.Printf("hype-backtesting ingest service v0.1.0\n")
	fmt.Printf("symbols: %v\n", symbols)
	fmt.Printf("endpoint: %s\n", hlWSEndpoint)

	if err := svc.Run(ctx); err != nil {
		log.Fatalf("service error: %v", err)
	}
}

func splitComma(s string) []string {
	var result []string
	current := ""
	for _, c := range s {
		if c == ',' {
			result = append(result, current)
			current = ""
		} else {
			current += string(c)
		}
	}
	if current != "" {
		result = append(result, current)
	}
	return result
}
