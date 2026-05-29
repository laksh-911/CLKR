import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createChart, ColorType } from 'lightweight-charts';

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

// ─── Onboarding Tutorial Step Definitions ───
const TUTORIAL_STEPS = [
  {
    id: 'command-center',
    title: 'The Command Center',
    subtitle: 'Header Bar',
    text: '1. Type a Ticker. Enter any stock (like SPY) to load data instantly.',
    targetSelector: '.ticker-input-wrapper',
    icon: '⌘',
  },
  {
    id: 'technical-intelligence',
    title: 'Technical Intelligence',
    subtitle: 'Main Canvas',
    text: '2. See Entry Points. Click directly on the chart to select your own entry points.',
    targetSelector: '.chart-viewport-wrapper',
    icon: '◈',
  },
  {
    id: 'strategy-engine',
    title: 'Strategy Engine',
    subtitle: 'Sidebar Bottom',
    text: '3. Run Backtest. Click \u2018Find My Strategy\u2019\u2014Boom, there\u2019s your setup!',
    targetSelector: '.find-strategy-btn',
    icon: '⚡',
  },
];

export default function App() {
  // --- State Management ---
  const [chartData, setChartData] = useState([]);
  const [pins, setPins] = useState([]);
  const [strategyResults, setStrategyResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [ticker, setTicker] = useState('SPY');
  const [tickerInput, setTickerInput] = useState('');
  const [error, setError] = useState(null);
  const [expandedStrategyIdx, setExpandedStrategyIdx] = useState(0);

  // --- Onboarding Tutorial State ---
  const [showTutorial, setShowTutorial] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [tooltipPos, setTooltipPos] = useState({ top: 0, left: 0, spotlightRect: null });
  const [tutorialReady, setTutorialReady] = useState(false);

  // --- Persistent Core References ---
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candlestickSeriesRef = useRef(null);
  const priceLinesRef = useRef({});
  const overlayLinesRef = useRef([]);

  // --- 1. Fetch Chart Data Pipeline ---
  const fetchChart = async (targetTicker) => {
    try {
      setLoading(true);
      setError(null);
      setPins([]);
      setStrategyResults(null);
      const response = await fetch(`${API_BASE}/api/chart?ticker=${targetTicker}`);
      if (!response.ok) {
        throw new Error('Ticker not found or invalid');
      }

      const data = await response.json();
      if (!data || !Array.isArray(data) || data.length === 0) {
        throw new Error('Ticker not found or invalid');
      }

      // Parse numeric values explicitly and force ascending chronological sort
      const formattedData = data.map(item => ({
        time: item.time || item.date,
        open: Number(item.open),
        high: Number(item.high),
        low: Number(item.low),
        close: Number(item.close),
      })).sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime());

      setChartData(formattedData);
      setTicker(targetTicker);
    } catch (err) {
      console.error("Error fetching ticker coordinates:", err);
      setError(err.message || 'Ticker not found or invalid');
      setChartData([]);
    } finally {
      setLoading(false);
    }
  };

  // Initial mount load
  useEffect(() => {
    fetchChart('SPY');
  }, []);

  // ─── Onboarding Tutorial Lifecycle ───
  const positionTooltip = useCallback(() => {
    if (!showTutorial) return;
    const step = TUTORIAL_STEPS[currentStep];
    if (!step) return;

    const targetEl = document.querySelector(step.targetSelector);
    if (!targetEl) return;

    const rect = targetEl.getBoundingClientRect();
    const tooltipWidth = 400;
    const tooltipHeight = 240;
    const gap = 16;

    let top, left;

    // Position logic: place tooltip where there is the most viewport space
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top;
    const spaceRight = window.innerWidth - rect.right;
    const spaceLeft = rect.left;

    if (spaceBelow >= tooltipHeight + gap) {
      // Below target
      top = rect.bottom + gap;
      left = rect.left + rect.width / 2 - tooltipWidth / 2;
    } else if (spaceAbove >= tooltipHeight + gap) {
      // Above target
      top = rect.top - tooltipHeight - gap;
      left = rect.left + rect.width / 2 - tooltipWidth / 2;
    } else if (spaceRight >= tooltipWidth + gap) {
      // Right of target
      top = rect.top + rect.height / 2 - tooltipHeight / 2;
      left = rect.right + gap;
    } else {
      // Left of target (fallback)
      top = rect.top + rect.height / 2 - tooltipHeight / 2;
      left = rect.left - tooltipWidth - gap;
    }

    // Clamp to viewport bounds
    top = Math.max(12, Math.min(top, window.innerHeight - tooltipHeight - 12));
    left = Math.max(12, Math.min(left, window.innerWidth - tooltipWidth - 12));

    setTooltipPos({
      top,
      left,
      spotlightRect: {
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
      },
    });
  }, [showTutorial, currentStep]);

  // Check localStorage on mount and trigger tutorial after a brief delay
  useEffect(() => {
    const hasCompleted = localStorage.getItem('clkr_onboarding_complete');
    if (!hasCompleted) {
      // Delay to let the DOM paint fully before measuring positions
      const timer = setTimeout(() => {
        setShowTutorial(true);
        setCurrentStep(0);
        setTutorialReady(true);
      }, 1200);
      return () => clearTimeout(timer);
    }
  }, []);

  // Reposition tooltip whenever step changes or window resizes
  useEffect(() => {
    if (!showTutorial) return;

    // Small delay for DOM to settle
    const raf = requestAnimationFrame(() => positionTooltip());
    window.addEventListener('resize', positionTooltip);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', positionTooltip);
    };
  }, [showTutorial, currentStep, positionTooltip]);

  const handleTutorialNext = () => {
    if (currentStep < TUTORIAL_STEPS.length - 1) {
      setCurrentStep(prev => prev + 1);
    }
  };

  const handleTutorialFinish = () => {
    setShowTutorial(false);
    setTutorialReady(false);
    localStorage.setItem('clkr_onboarding_complete', 'true');
  };

  // --- 2. Initialize and Manage Lightweight Charts ---
  useEffect(() => {
    // Safety check: container must exist and data must have populated coordinates
    if (!chartContainerRef.current) return;
    if (error || !chartData || chartData.length === 0) {
      chartContainerRef.current.innerHTML = '';
      return;
    }

    let chart;
    try {
      // Clear any leftover DOM canvas nodes from React StrictMode double-mount
      chartContainerRef.current.innerHTML = '';

      // Create TradingView engine on the LOCAL variable (not on a ref)
      chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: '#0B0C0E' },
          textColor: '#64748B',
          fontFamily: "'JetBrains Mono', monospace",
        },
        grid: {
          vertLines: { color: 'rgba(255, 255, 255, 0.02)' },
          horzLines: { color: 'rgba(255, 255, 255, 0.02)' },
        },
        width: chartContainerRef.current.clientWidth,
        height: chartContainerRef.current.clientHeight || 480,
        timeScale: {
          borderColor: 'rgba(255, 255, 255, 0.05)',
          timeVisible: true,
          secondsVisible: false,
        },
        rightPriceScale: {
          borderColor: 'rgba(255, 255, 255, 0.05)',
        },
        crosshair: {
          vertLine: {
            color: 'rgba(255, 255, 255, 0.25)',
            width: 1,
            style: 2, // dashed
            labelBackgroundColor: '#1E293B',
          },
          horzLine: {
            color: 'rgba(255, 255, 255, 0.25)',
            width: 1,
            style: 2, // dashed
            labelBackgroundColor: '#1E293B',
          },
        },
      });

      // Initialize Candlestick Series directly on the local chart instance (v4 API)
      const candlestickSeries = chart.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderVisible: false,
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
      });

      // Load structured candle array coordinates
      candlestickSeries.setData(chartData);

      // Store references for secondary hooks
      chartRef.current = chart;
      candlestickSeriesRef.current = candlestickSeries;

      // Sync existing markers on initial paint
      if (pins.length > 0) {
        const markers = pins
          .slice()
          .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
          .map(pin => ({
            time: pin.date,
            position: 'belowBar',
            color: '#D4AF37',
            shape: 'arrowUp',
            text: `$${pin.price.toFixed(2)}`,
            size: 1.5,
          }));
        candlestickSeries.setMarkers(markers);
      }
    } catch (e) {
      console.error("Error initializing lightweight-charts:", e);
      setError("Failed to render chart canvas");
      return;
    }

    // Handle viewport fluid layout adjustment on window resize
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        try {
          chartRef.current.applyOptions({
            width: chartContainerRef.current.clientWidth,
          });
        } catch (e) {
          console.error("Error resizing chart:", e);
        }
      }
    };
    window.addEventListener('resize', handleResize);

    // ============================================
    // CLEANUP: Strict lifecycle dismantling guard
    // ============================================
    return () => {
      window.removeEventListener('resize', handleResize);
      if (chart) {
        try {
          chart.remove();
        } catch (e) {
          console.error("Error removing chart:", e);
        }
      }
      chartRef.current = null;
      candlestickSeriesRef.current = null;
      priceLinesRef.current = {};
      overlayLinesRef.current = [];
    };
  }, [chartData, error]);

  // --- 3. Interactive Click Mapping via subscribeClick ---
  useEffect(() => {
    if (!chartRef.current || !candlestickSeriesRef.current) return;

    const handleSubscribeClick = (param) => {
      if (!param || !param.time || !param.point) return;

      // Extract candle data from the series prices map
      const seriesData = param.seriesPrices || param.seriesData;
      if (!seriesData) return;

      const price = seriesData.get(candlestickSeriesRef.current);
      if (!price) return;

      // Format time into YYYY-MM-DD string
      let dateStr;
      if (typeof param.time === 'string') {
        dateStr = param.time;
      } else if (typeof param.time === 'object' && param.time.year) {
        dateStr = `${param.time.year}-${String(param.time.month).padStart(2, '0')}-${String(param.time.day).padStart(2, '0')}`;
      } else {
        dateStr = new Date(param.time * 1000).toISOString().split('T')[0];
      }

      const closePrice = parseFloat((price.close || price.open || price).toFixed(2));

      // Toggle mechanism: add if new, remove if clicked again
      setPins((prevPins) => {
        const exists = prevPins.some((p) => p.date === dateStr);
        if (exists) {
          return prevPins.filter((p) => p.date !== dateStr);
        } else {
          return [...prevPins, { date: dateStr, price: closePrice }]
            .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
        }
      });
    };

    chartRef.current.subscribeClick(handleSubscribeClick);

    return () => {
      if (chartRef.current) {
        chartRef.current.unsubscribeClick(handleSubscribeClick);
      }
    };
  }, [chartData]);

  // --- 4. Render Markers and Horizontal Price Tracking Lines ---
  useEffect(() => {
    if (!candlestickSeriesRef.current) return;

    // Build sorted markers array (lightweight-charts requires ascending order)
    const sortedPins = pins
      .slice()
      .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());

    const markers = sortedPins.map(pin => ({
      time: pin.date,
      position: 'belowBar',
      color: '#D4AF37',
      shape: 'arrowUp',
      text: `$${pin.price.toFixed(2)}`,
      size: 1.5,
    }));
    candlestickSeriesRef.current.setMarkers(markers);

    // Clear stale horizontal price lines
    Object.values(priceLinesRef.current).forEach(line => {
      if (candlestickSeriesRef.current) {
        candlestickSeriesRef.current.removePriceLine(line);
      }
    });
    priceLinesRef.current = {};

    // Redraw updated price tracking crosshairs
    sortedPins.forEach(pin => {
      if (!candlestickSeriesRef.current) return;
      const line = candlestickSeriesRef.current.createPriceLine({
        price: pin.price,
        color: 'rgba(212, 175, 55, 0.35)',
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: `Entry (${pin.date})`,
      });
      priceLinesRef.current[pin.date] = line;
    });
  }, [pins]);

  // --- 5. Draw Client-Side Strategy Overlays (Moving Averages) ---
  useEffect(() => {
    if (!chartRef.current || !candlestickSeriesRef.current || !strategyResults || chartData.length === 0) return;

    // Clear preceding strategy indicator lines
    overlayLinesRef.current.forEach(line => {
      if (chartRef.current) chartRef.current.removeSeries(line);
    });
    overlayLinesRef.current = [];

    // Inject trend-lines sent back by the analysis engine
    if (strategyResults.indicators) {
      Object.entries(strategyResults.indicators).forEach(([name, points]) => {
        if (!chartRef.current) return;

        const lineSeries = chartRef.current.addLineSeries({
          color: name.includes('Fast') ? '#D4AF37' : '#64748B',
          lineWidth: 2,
          title: name,
        });

        const formattedPoints = points
          .filter(p => p.value !== null && p.value !== undefined)
          .map(p => ({ time: p.date || p.time, value: p.value }));

        lineSeries.setData(formattedPoints);
        overlayLinesRef.current.push(lineSeries);
      });
    }
  }, [strategyResults, chartData]);

  // --- Helper Functions for Client-Side Indicators ---
  const calculateSMA = (data, windowSize) => {
    let r = [];
    for (let i = 0; i < data.length; i++) {
      if (i < windowSize - 1) {
        r.push({ time: data[i].time, value: null });
      } else {
        let sum = 0;
        for (let j = 0; j < windowSize; j++) {
          sum += data[i - j].close;
        }
        r.push({ time: data[i].time, value: sum / windowSize });
      }
    }
    return r;
  };

  const calculateEMA = (data, windowSize) => {
    let r = [];
    if (data.length === 0) return r;
    let k = 2 / (windowSize + 1);
    let ema = data[0].close;
    r.push({ time: data[0].time, value: ema });
    for (let i = 1; i < data.length; i++) {
      ema = data[i].close * k + ema * (1 - k);
      r.push({ time: data[i].time, value: ema });
    }
    return r;
  };

  // --- 6. Strategy Analysis Handler ---
  const handleRunStrategy = async () => {
    if (pins.length === 0) return;
    try {
      setLoading(true);
      
      // 1. Fetch analysis results for UI statistics & chart overlay
      const analyzeResponse = await fetch(`${API_BASE}/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker: ticker,
          pins: pins.map(p => p.date)
        }),
      });
      if (!analyzeResponse.ok) throw new Error('Analysis pipeline returned error');
      
      const data = await analyzeResponse.json();
      
      const mappedStrategies = data.strategies.map(strat => ({
        ...strat,
        combined_score: strat.final_score,
        backtest: {
          win_rate: strat.win_rate,
          profit_factor: strat.profit_factor,
          total_trades: strat.total_trades,
          avg_return: strat.total_return,
          trades: strat.trades ? strat.trades.map(t => ({
            ...t,
            return_pct: t.return
          })) : []
        }
      }));

      const indicators = {};
      if (mappedStrategies.length > 0) {
        const topStrat = mappedStrategies[0];
        let trendRuleCount = 0;
        topStrat.rules.forEach((rule) => {
          if (rule.type === 'sma_cross') {
            const w = rule.params?.window || 20;
            const name = trendRuleCount === 0 ? `Fast SMA (${w})` : `Slow SMA (${w})`;
            indicators[name] = calculateSMA(chartData, w);
            trendRuleCount++;
          } else if (rule.type === 'ema_cross') {
            const w = rule.params?.window || 20;
            const name = trendRuleCount === 0 ? `Fast EMA (${w})` : `Slow EMA (${w})`;
            indicators[name] = calculateEMA(chartData, w);
            trendRuleCount++;
          }
        });
      }

      setStrategyResults({
        strategies: mappedStrategies,
        indicators: indicators
      });
      setExpandedStrategyIdx(0);

      // 2. Fetch export results for actual strategy pack ZIP file download (Preserving core logic exactly)
      const response = await fetch(`${API_BASE}/api/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker: ticker,
          strategy: {
            pins: pins
          }
        }),
      });
      if (!response.ok) throw new Error('Export pipeline returned error');
      
      // Process binary ZIP blob download
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'quant_strategy_package.zip';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

    } catch (error) {
      console.error("Strategy analysis failed:", error);
    } finally {
      setLoading(false);
    }
  };

  // --- 7. Strategy Pack Download Handler ---
  const handleDownloadPack = async () => {
    if (!strategyResults || !strategyResults.strategies || strategyResults.strategies.length === 0) return;
    try {
      const topStrategy = strategyResults.strategies[0];
      const response = await fetch(`${API_BASE}/api/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker: ticker,
          strategy: topStrategy,
        }),
      });
      if (!response.ok) throw new Error('Export pipeline returned error');
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${ticker}_strategy_pack.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Strategy pack download failed:", error);
    }
  };

  // --- Remove a single pin ---
  const removePin = (dateToRemove) => {
    setPins(prev => prev.filter(p => p.date !== dateToRemove));
  };

  // =========================================
  // JSX RETURN — Premium Dark Mode Dashboard
  // =========================================
  // Current tutorial step data (safe access)
  const activeStep = TUTORIAL_STEPS[currentStep] || null;

  return (
    <div className="app-container">
      {/* ─── Onboarding Tutorial Overlay ─── */}
      {showTutorial && tutorialReady && activeStep && tooltipPos.spotlightRect && (
        <>
          {/* Backdrop overlay with spotlight cutout */}
          <div className="tutorial-overlay" onClick={(e) => e.stopPropagation()}>
            {/* SVG mask to cut out the spotlight area */}
            <svg className="tutorial-overlay-svg" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <mask id="tutorial-spotlight-mask">
                  <rect x="0" y="0" width="100%" height="100%" fill="white" />
                  <rect
                    x={tooltipPos.spotlightRect.left - 6}
                    y={tooltipPos.spotlightRect.top - 6}
                    width={tooltipPos.spotlightRect.width + 12}
                    height={tooltipPos.spotlightRect.height + 12}
                    rx="10"
                    ry="10"
                    fill="black"
                  />
                </mask>
              </defs>
              <rect
                x="0" y="0" width="100%" height="100%"
                fill="rgba(0, 0, 0, 0.72)"
                mask="url(#tutorial-spotlight-mask)"
              />
            </svg>

            {/* Spotlight border glow ring */}
            <div
              className="tutorial-spotlight-ring"
              style={{
                top: tooltipPos.spotlightRect.top - 6,
                left: tooltipPos.spotlightRect.left - 6,
                width: tooltipPos.spotlightRect.width + 12,
                height: tooltipPos.spotlightRect.height + 12,
              }}
            />
          </div>

          {/* Tooltip Capsule */}
          <div
            className="tutorial-tooltip"
            style={{
              top: tooltipPos.top,
              left: tooltipPos.left,
            }}
          >
            {/* Step indicator pips */}
            <div className="tutorial-step-pips">
              {TUTORIAL_STEPS.map((_, idx) => (
                <div
                  key={idx}
                  className={`tutorial-pip ${idx === currentStep ? 'active' : ''} ${idx < currentStep ? 'completed' : ''}`}
                />
              ))}
              <span className="tutorial-step-counter">
                {currentStep + 1} / {TUTORIAL_STEPS.length}
              </span>
            </div>

            {/* Header */}
            <div className="tutorial-tooltip-header">
              <span className="tutorial-tooltip-icon">{activeStep.icon}</span>
              <div>
                <div className="tutorial-tooltip-title">{activeStep.title}</div>
                <div className="tutorial-tooltip-subtitle">{activeStep.subtitle}</div>
              </div>
            </div>

            {/* Body text */}
            <p className="tutorial-tooltip-body">{activeStep.text}</p>

            {/* Navigation controls */}
            <div className="tutorial-tooltip-actions">
              <button
                className="tutorial-btn tutorial-btn-skip"
                onClick={handleTutorialFinish}
              >
                Skip
              </button>
              {currentStep < TUTORIAL_STEPS.length - 1 ? (
                <button
                  className="tutorial-btn tutorial-btn-next"
                  onClick={handleTutorialNext}
                >
                  Next →
                </button>
              ) : (
                <button
                  className="tutorial-btn tutorial-btn-launch"
                  onClick={handleTutorialFinish}
                >
                  ⚡ Launch Terminal
                </button>
              )}
            </div>
          </div>
        </>
      )}
      {/* ─── Top Navigation Header ─── */}
      <header className="header">
        <div className="logo-section">
          <div className="logo-text">
            CLKR
          </div>
        </div>
        <div className="search-section">
          <div className="ticker-input-wrapper">
            <span className="ticker-icon"></span>
            <input
              id="ticker-search"
              type="text"
              className="ticker-input"
              placeholder="Ticker..."
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const val = document.getElementById('ticker-search').value.trim().toUpperCase();
                  if (val) fetchChart(val);
                }
              }}
            />
          </div>
          <button
            className="load-btn"
            onClick={() => {
              const val = document.getElementById('ticker-search').value.trim().toUpperCase();
              if (val) fetchChart(val);
            }}
          >
            Load
          </button>
          <span className="active-ticker-badge">
            ACTIVE: {ticker}
          </span>
        </div>
      </header>

      {/* ─── Main Dashboard Grid ─── */}
      <div className="dashboard-grid">
        {/* ── Left Sidebar: Controls & Pin Log ── */}
        <div className="sidebar">
          {/* KPI Block Container */}
          <div className="glass-panel">
            <div className="kpi-card">
              <span className="kpi-label">Pins Locked</span>
              <div className="kpi-val">{pins.length}</div>
            </div>
          </div>

          {/* Pin List Scrollable Log */}
          <div className="glass-panel" style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div className="panel-title">
              Live Anchors Log
            </div>
            <div className="pin-list-container" style={{ flex: 1, maxHeight: 'none' }}>
              {pins.length === 0 ? (
                <div className="empty-pins-msg">
                  Click candles on the chart to drop entry pins
                </div>
              ) : (
                pins.map((pin) => (
                  <div key={pin.date} className="pin-item">
                    <div className="pin-info">
                      <span className="pin-date">{pin.date}</span>
                      <span className="pin-price">${pin.price.toFixed(2)}</span>
                    </div>
                    <button
                      className="delete-pin-btn"
                      onClick={() => removePin(pin.date)}
                      title="Remove pin"
                    >
                      X
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Strategy Results Panel */}
          {strategyResults && strategyResults.strategies && strategyResults.strategies.length > 0 && (
            <div className="glass-panel">
              <div className="panel-title">
                Top Strategies
              </div>
              <div className="results-container">
                {strategyResults.strategies.slice(0, 3).map((strat, idx) => (
                  <div
                    key={idx}
                    className={`strategy-card ${idx === 0 ? 'selected' : ''}`}
                    onClick={() => setExpandedStrategyIdx(expandedStrategyIdx === idx ? -1 : idx)}
                  >
                    <div className="strategy-rank">
                      <span className={`rank-badge rank-${idx + 1}`}>
                        #{idx + 1}
                      </span>
                      <span className="score-badge">
                        {(strat.combined_score * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="strategy-name">{strat.name || strat.description}</div>
                    <div className="metrics-row">
                      <div className="metric-item">
                        <span className="metric-label">Win Rate</span>
                        <span className="metric-val">
                          {((strat.backtest?.win_rate || 0) * 100).toFixed(1)}%
                        </span>
                      </div>
                      <div className="metric-item">
                        <span className="metric-label">Profit Factor</span>
                        <span className="metric-val">
                          {(strat.backtest?.profit_factor || 0).toFixed(2)}
                        </span>
                      </div>
                      <div className="metric-item">
                        <span className="metric-label">Total Trades</span>
                        <span className="metric-val">
                          {strat.backtest?.total_trades || 0}
                        </span>
                      </div>
                      <div className="metric-item">
                        <span className="metric-label">Avg Return</span>
                        <span className="metric-val" style={{
                          color: (strat.backtest?.avg_return || 0) >= 0
                            ? 'var(--accent-green)' : 'var(--accent-red)',
                        }}>
                          {((strat.backtest?.avg_return || 0) * 100).toFixed(2)}%
                        </span>
                      </div>
                    </div>

                    {/* AI Insight Accordion */}
                    <div
                      className={`ai-insight-accordion ${expandedStrategyIdx === idx ? 'open' : ''}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpandedStrategyIdx(expandedStrategyIdx === idx ? -1 : idx);
                      }}
                    >
                      <div className="ai-insight-header">
                        <span className="ai-insight-label">✦ AI Insight</span>
                        <span className="ai-insight-chevron">
                          {expandedStrategyIdx === idx ? '▲' : '▼'}
                        </span>
                      </div>
                      <div className="ai-insight-content">
                        {strat.ai_brief ? (
                          <p className="ai-insight-text">{strat.ai_brief}</p>
                        ) : (
                          <div className="ai-insight-loading">
                            <span className="ai-insight-pulse-text">AI Analysing...</span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <button className="download-pack-btn" onClick={handleDownloadPack}>
                Download Strategy Pack
              </button>
            </div>
          )}

          {/* Strategy Action Button */}
          <button
            className="find-strategy-btn"
            disabled={pins.length === 0 || loading}
            onClick={handleRunStrategy}
          >
            {loading ? 'Processing...' : 'Find My Strategy'}
          </button>
        </div>

        {/* ── Right: Interactive Chart Workspace ── */}
        <div className="chart-panel-container">
          {/* Chart Header Bar */}
          <div className="chart-header">
            <div className="chart-ticker-title">
              <span style={{ color: 'var(--accent-gold)' }}>Active:</span>
              {ticker}
              <span style={{
                fontSize: '11px',
                color: 'var(--text-secondary)',
                fontWeight: 400,
              }}>
                · {chartData.length} bars
              </span>
            </div>
            <div className="chart-instructions">
              Click candles to pin entry points
            </div>
          </div>

          {/* Chart Canvas Viewport */}
          <div className="chart-viewport-wrapper">
            {loading && (
              <div className="loading-overlay">
                <div className="spinner" />
                <span className="loading-text">Synchronizing market data...</span>
              </div>
            )}
            {error ? (
              <div className="chart-error-fallback">
                <div className="error-message-box">
                  <span className="error-icon">!</span>
                  <span className="error-title">Ticker not found or invalid</span>
                  <span className="error-desc">Please verify the search query and try again.</span>
                </div>
              </div>
            ) : (
              <div
                ref={chartContainerRef}
                className="chart-instance"
              />
            )}
          </div>

          {/* Bottom Trade Log Panel (visible when strategy results exist) */}
          {strategyResults && strategyResults.strategies && strategyResults.strategies[0]?.backtest?.trades && (
            <div className="bottom-trade-log-panel">
              <div className="trade-log-header">
                <span>Backtest Trade Log — {strategyResults.strategies[0].name}</span>
                <span style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>
                  {strategyResults.strategies[0].backtest.trades.length} trades
                </span>
              </div>
              <div className="trade-log-table-wrapper">
                <table className="trade-log-table">
                  <thead>
                    <tr>
                      <th>Entry Date</th>
                      <th>Entry Price</th>
                      <th>Exit Date</th>
                      <th>Exit Price</th>
                      <th>Return</th>
                    </tr>
                  </thead>
                  <tbody>
                    {strategyResults.strategies[0].backtest.trades.slice(0, 30).map((trade, idx) => (
                      <tr key={idx}>
                        <td>{trade.entry_date}</td>
                        <td>${trade.entry_price?.toFixed(2)}</td>
                        <td>{trade.exit_date}</td>
                        <td>${trade.exit_price?.toFixed(2)}</td>
                        <td className={trade.return_pct >= 0 ? 'trade-return-pos' : 'trade-return-neg'}>
                          {(trade.return_pct * 100).toFixed(2)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}