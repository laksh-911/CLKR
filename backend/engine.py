import pandas as pd
import numpy as np
import yfinance as yf
import json
import io
import zipfile
import os

try:
    from google import genai
    client = genai.Client()
except Exception as e:
    client = None

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    # Wilder's smoothing using EMA
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_macd(series: pd.Series, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
    fast_ema = series.ewm(span=fast_period, adjust=False).mean()
    slow_ema = series.ewm(span=slow_period, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    macd_hist = macd_line - signal_line
    return macd_line, signal_line, macd_hist

def get_chart_data(ticker: str):
    df = yf.download(ticker, period="2y")
    if df.empty:
        return None
    
    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    # Ensure index is reset into a proper column before formatting
    if 'Date' not in df.columns:
        df = df.reset_index()
        
    # Standardize column names to ensure 'Date' exists
    if 'Date' not in df.columns:
        date_col = None
        for col in df.columns:
            if str(col).lower() in ['date', 'datetime', 'index']:
                date_col = col
                break
        if date_col is not None:
            df = df.rename(columns={date_col: 'Date'})
        else:
            # Fallback: check if the index itself is datetime-like
            if isinstance(df.index, pd.DatetimeIndex):
                df['Date'] = df.index
            else:
                # Look for any datetime64 column
                for col in df.columns:
                    if pd.api.types.is_datetime64_any_dtype(df[col]):
                        df = df.rename(columns={col: 'Date'})
                        break

    if 'Date' in df.columns:
        # Convert to datetime if it's not already
        if not pd.api.types.is_datetime64_any_dtype(df['Date']):
            df['Date'] = pd.to_datetime(df['Date'])
        # Format Date column to string
        df['DateStr'] = df['Date'].dt.strftime('%Y-%m-%d')
    else:
        # If still not found, fallback to index values formatted to string
        if isinstance(df.index, pd.DatetimeIndex):
            df['DateStr'] = df.index.strftime('%Y-%m-%d')
        else:
            # Absolute fallback: convert index to string
            df['DateStr'] = df.index.astype(str)
            
    return df


def run_backtest(df: pd.DataFrame, signals: pd.Series, holding_period: int = 15, stop_loss_pct: float = -0.05, take_profit_pct: float = 0.15):
    """
    Runs a single-position state-machine backtester.
    Once a position is entered, subsequent signals are ignored until the position is closed.
    """
    close = df['Close'].values
    dates = df['DateStr'].values
    n = len(df)
    
    position_active = False
    entry_idx = -1
    entry_price = 0.0
    
    trades = []
    
    for i in range(n):
        if not position_active:
            if signals.iloc[i]:
                position_active = True
                entry_idx = i
                entry_price = close[i]
        else:
            current_price = close[i]
            price_change = (current_price - entry_price) / entry_price
            days_held = i - entry_idx
            
            # Exit triggers
            if price_change <= stop_loss_pct:
                trades.append({
                    'entry_date': str(dates[entry_idx]),
                    'exit_date': str(dates[i]),
                    'entry_price': float(entry_price),
                    'exit_price': float(current_price),
                    'return': float(price_change),
                    'exit_reason': 'Stop Loss'
                })
                position_active = False
            elif price_change >= take_profit_pct:
                trades.append({
                    'entry_date': str(dates[entry_idx]),
                    'exit_date': str(dates[i]),
                    'entry_price': float(entry_price),
                    'exit_price': float(current_price),
                    'return': float(price_change),
                    'exit_reason': 'Take Profit'
                })
                position_active = False
            elif days_held >= holding_period:
                trades.append({
                    'entry_date': str(dates[entry_idx]),
                    'exit_date': str(dates[i]),
                    'entry_price': float(entry_price),
                    'exit_price': float(current_price),
                    'return': float(price_change),
                    'exit_reason': 'Holding Period'
                })
                position_active = False
                
    # Close open trade on final bar
    if position_active:
        last_idx = n - 1
        current_price = close[last_idx]
        price_change = (current_price - entry_price) / entry_price
        trades.append({
            'entry_date': str(dates[entry_idx]),
            'exit_date': str(dates[last_idx]),
            'entry_price': float(entry_price),
            'exit_price': float(current_price),
            'return': float(price_change),
            'exit_reason': 'End of Data'
        })
        
    return trades

def sweep_strategies(df: pd.DataFrame, pinned_dates: list):
    # Convert dates to dataframe indices
    pin_indices = []
    df_dates = df['DateStr'].tolist()
    for pd_str in pinned_dates:
        try:
            target = pd.to_datetime(pd_str)
            # find index of closest date
            closest_idx = np.abs(pd.to_datetime(df['DateStr']) - target).argmin()
            pin_indices.append(int(closest_idx))
        except Exception:
            continue
            
    if not pin_indices:
        return []

    # 1. Pre-calculate indicators vectorially
    sma_windows = [5, 10, 15, 20, 30, 45, 50, 75, 100, 150, 200]
    ema_windows = [5, 10, 15, 20, 30, 45, 50, 75, 100, 150, 200]
    rsi_windows = [7, 9, 11, 14, 18, 21]
    rsi_levels = [25, 30, 35, 40, 45]
    
    # Calculate Base Columns
    for w in sma_windows:
        df[f'sma_{w}'] = df['Close'].rolling(window=w).mean()
    for w in ema_windows:
        df[f'ema_{w}'] = df['Close'].ewm(span=w, adjust=False).mean()
    for w in rsi_windows:
        df[f'rsi_{w}'] = calculate_rsi(df['Close'], w)
        
    macd_line, signal_line, macd_hist = calculate_macd(df['Close'])
    df['macd_line'] = macd_line
    df['macd_signal'] = signal_line
    df['macd_hist'] = macd_hist

    # Generate basic rule signals (boolean Series)
    basic_rules = []
    
    # SMA crossovers
    for w in sma_windows:
        col_name = f'sig_sma_cross_{w}'
        df[col_name] = (df['Close'] > df[f'sma_{w}']) & (df['Close'].shift(1) <= df[f'sma_{w}'].shift(1))
        basic_rules.append({
            'id': f'sma_cross_{w}',
            'name': f'Price Crosses Above SMA {w}',
            'col': col_name,
            'complexity': 1.0,
            'indicator_type': 'sma_cross',
            'params': {'window': w}
        })
        
    # EMA crossovers
    for w in ema_windows:
        col_name = f'sig_ema_cross_{w}'
        df[col_name] = (df['Close'] > df[f'ema_{w}']) & (df['Close'].shift(1) <= df[f'ema_{w}'].shift(1))
        basic_rules.append({
            'id': f'ema_cross_{w}',
            'name': f'Price Crosses Above EMA {w}',
            'col': col_name,
            'complexity': 1.0,
            'indicator_type': 'ema_cross',
            'params': {'window': w}
        })
        
    # RSI below threshold
    for w in rsi_windows:
        for l in rsi_levels:
            col_name = f'sig_rsi_below_{w}_{l}'
            df[col_name] = df[f'rsi_{w}'] < l
            basic_rules.append({
                'id': f'rsi_below_{w}_{l}',
                'name': f'RSI {w} is Below {l}',
                'col': col_name,
                'complexity': 1.0,
                'indicator_type': 'rsi_below',
                'params': {'window': w, 'level': l}
            })
            
    # RSI cross above threshold
    for w in rsi_windows:
        for l in rsi_levels:
            col_name = f'sig_rsi_cross_{w}_{l}'
            df[col_name] = (df[f'rsi_{w}'] > l) & (df[f'rsi_{w}'].shift(1) <= l)
            basic_rules.append({
                'id': f'rsi_cross_{w}_{l}',
                'name': f'RSI {w} Crosses Above {l}',
                'col': col_name,
                'complexity': 1.0,
                'indicator_type': 'rsi_cross',
                'params': {'window': w, 'level': l}
            })
            
    # MACD standard crossovers
    df['sig_macd_cross'] = (df['macd_line'] > df['macd_signal']) & (df['macd_line'].shift(1) <= df['macd_signal'].shift(1))
    basic_rules.append({
        'id': 'macd_cross',
        'name': 'MACD Line Crosses Above Signal',
        'col': 'sig_macd_cross',
        'complexity': 1.0,
        'indicator_type': 'macd_cross',
        'params': {}
    })
    
    df['sig_macd_hist_cross'] = (df['macd_hist'] > 0) & (df['macd_hist'].shift(1) <= 0)
    basic_rules.append({
        'id': 'macd_hist_cross',
        'name': 'MACD Histogram Crosses Above 0',
        'col': 'sig_macd_hist_cross',
        'complexity': 1.0,
        'indicator_type': 'macd_hist_cross',
        'params': {}
    })

    # Prepare Candidate Strategies: Basic rules and dual-condition rules
    # Dual-condition rules combine a Trend Rule (SMA/EMA/MACD cross) and a Momentum Rule (RSI/MACD)
    trend_cols = [r for r in basic_rules if r['indicator_type'] in ['sma_cross', 'ema_cross', 'macd_cross']]
    momentum_cols = [r for r in basic_rules if r['indicator_type'] in ['rsi_below', 'rsi_cross', 'macd_hist_cross', 'macd_cross']]
    
    candidates = []
    # Add all basic rules
    for br in basic_rules:
        candidates.append({
            'id': br['id'],
            'name': br['name'],
            'rules': [br],
            'complexity': br['complexity']
        })
        
    # Add combinations (Limit selection to logical combinations to keep search clean)
    for tc in trend_cols:
        for mc in momentum_cols:
            if tc['id'] != mc['id']:
                candidates.append({
                    'id': f"{tc['id']}_AND_{mc['id']}",
                    'name': f"{tc['name']} AND {mc['name']}",
                    'rules': [tc, mc],
                    'complexity': 2.0
                })

    results = []
    
    # Pre-extract slices of signals for pins to do extremely fast IS scoring
    # This prevents running slow loops for zero-match candidates
    for cand in candidates:
        # Calculate boolean intersection of candidate rules
        if len(cand['rules']) == 1:
            signals = df[cand['rules'][0]['col']]
        else:
            signals = df[cand['rules'][0]['col']] & df[cand['rules'][1]['col']]
            
        # 1. In-Sample (IS) Pin Matching Score
        matched_pins = 0
        for idx in pin_indices:
            # 3-day tolerance check
            window_slice = signals.iloc[max(0, idx - 3):idx + 1]
            if window_slice.any():
                matched_pins += 1
                
        is_score = matched_pins / len(pin_indices)
        
        # Optimization: Only run full backtest if there is at least one match
        if is_score == 0:
            continue
            
        # 2. Run Backtest
        trades = run_backtest(df, signals)
        total_trades = len(trades)
        
        # Calculate Out-of-Sample metrics
        if total_trades > 0:
            profitable_trades = sum(1 for t in trades if t['return'] > 0)
            win_rate = profitable_trades / total_trades
            gross_profit = sum(t['return'] for t in trades if t['return'] > 0)
            gross_loss = sum(abs(t['return']) for t in trades if t['return'] <= 0)
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0
            
            # Compound return
            returns_prod = 1.0
            for t in trades:
                returns_prod *= (1.0 + t['return'])
            total_return = returns_prod - 1.0
        else:
            win_rate = 0.0
            profit_factor = 0.0
            total_return = 0.0
            
        # 3. Apply Penalties
        # Complexity penalty: 0.15 for 2 rules
        complexity_penalty = 0.15 if cand['complexity'] > 1.0 else 0.0
        
        # Rare signal penalty: less than 6 trades in 2 years is penalized by 0.40
        rare_signal_penalty = 0.40 if total_trades < 6 else 0.0
        
        # 4. Final Balanced Scoring Formula
        final_score = (0.5 * is_score) + (0.5 * win_rate) - complexity_penalty - rare_signal_penalty
        # Clamp score between -1.0 and 1.0
        final_score = max(-1.0, min(1.0, final_score))
        
        results.append({
            'id': cand['id'],
            'name': cand['name'],
            'rules': [{'name': r['name'], 'type': r['indicator_type'], 'params': r['params']} for r in cand['rules']],
            'is_score': float(is_score),
            'win_rate': float(win_rate),
            'profit_factor': float(profit_factor),
            'total_return': float(total_return),
            'total_trades': total_trades,
            'final_score': float(final_score),
            'trades': trades[:15] # Return first 15 trades for dashboard review
        })
        
    # Sort results by final score descending
    results = sorted(results, key=lambda x: x['final_score'], reverse=True)
    return results[:3] # Return top 3 candidates

def generate_pine_script(ticker: str, strategy_config: dict) -> str:
    """
    Generates a TradingView Pine Script v5 file based on a rigid compile-ready template.
    """
    rules = strategy_config.get('rules', [])
    
    declarations = []
    conditions = []
    
    for idx, rule in enumerate(rules):
        r_type = rule['type']
        params = rule['params']
        suffix = f"_{idx}"
        
        if r_type == 'sma_cross':
            w = params.get('window', 20)
            declarations.append(f"sma{suffix} = ta.sma(close, {w})")
            conditions.append(f"ta.crossover(close, sma{suffix})")
        elif r_type == 'ema_cross':
            w = params.get('window', 20)
            declarations.append(f"ema{suffix} = ta.ema(close, {w})")
            conditions.append(f"ta.crossover(close, ema{suffix})")
        elif r_type == 'rsi_below':
            w = params.get('window', 14)
            l = params.get('level', 30)
            declarations.append(f"rsi{suffix} = ta.rsi(close, {w})")
            conditions.append(f"rsi{suffix} < {l}")
        elif r_type == 'rsi_cross':
            w = params.get('window', 14)
            l = params.get('level', 30)
            declarations.append(f"rsi{suffix} = ta.rsi(close, {w})")
            conditions.append(f"ta.crossover(rsi{suffix}, {l})")
        elif r_type == 'macd_cross':
            declarations.append(f"[macdLine{suffix}, signalLine{suffix}, _] = ta.macd(close, 12, 26, 9)")
            conditions.append(f"ta.crossover(macdLine{suffix}, signalLine{suffix})")
        elif r_type == 'macd_hist_cross':
            declarations.append(f"[_, _, macdHist{suffix}] = ta.macd(close, 12, 26, 9)")
            conditions.append(f"ta.crossover(macdHist{suffix}, 0)")
            
    decl_str = "\n".join(declarations)
    cond_str = " and ".join(conditions) if conditions else "false"
    
    template = f"""//@version=5
strategy("Reverse Engineered Strategy: {ticker}", overlay=true, initial_capital=10000, default_qty_type=strategy.percent_of_equity, default_qty_value=100)

// Backtesting Window Parameters
holdingPeriod = input.int(15, title="Holding Period (bars)")
stopLossPct = input.float(5.0, title="Stop Loss %") / 100.0
takeProfitPct = input.float(15.0, title="Take Profit %") / 100.0

// Technical Indicator Declarations
{decl_str}

// Buy Condition
buyCondition = {cond_str}

// Trade State Machine (Position Tracker)
inPosition = strategy.position_size > 0

var int entryBar = na
var float entryPrice = na

if inPosition
    if na(entryBar)
        entryBar := bar_index
        entryPrice := strategy.position_avg_price
else
    entryBar := na
    entryPrice := na

if not inPosition
    if buyCondition
        strategy.entry("Buy", strategy.long)
        alert("BUY " + syminfo.ticker + " at " + str.tostring(close), alert.freq_once_per_bar)
else
    daysHeld = bar_index - entryBar
    priceChange = (close - entryPrice) / entryPrice
    
    stopTrigger = priceChange <= -stopLossPct
    tpTrigger = priceChange >= takeProfitPct
    holdTrigger = daysHeld >= holdingPeriod
    
    if stopTrigger or tpTrigger or holdTrigger
        exitReason = stopTrigger ? "Stop Loss" : tpTrigger ? "Take Profit" : "Holding Period"
        strategy.close("Buy", comment = exitReason)
        alert("SELL " + syminfo.ticker + " at " + str.tostring(close) + " Reason: " + exitReason, alert.freq_once_per_bar)
"""
    return template

def generate_python_script(ticker: str, strategy_config: dict) -> str:
    """
    Generates a production-ready Pandas backtesting Python script.
    """
    rules = strategy_config.get('rules', [])
    
    calc_lines = []
    conditions = []
    
    for idx, rule in enumerate(rules):
        r_type = rule['type']
        params = rule['params']
        suffix = f"_{idx}"
        
        if r_type == 'sma_cross':
            w = params.get('window', 20)
            calc_lines.append(f"df['sma{suffix}'] = df['Close'].rolling(window={w}).mean()")
            conditions.append(f"(df['Close'] > df['sma{suffix}']) & (df['Close'].shift(1) <= df['sma{suffix}'].shift(1))")
        elif r_type == 'ema_cross':
            w = params.get('window', 20)
            calc_lines.append(f"df['ema{suffix}'] = df['Close'].ewm(span={w}, adjust=False).mean()")
            conditions.append(f"(df['Close'] > df['ema{suffix}']) & (df['Close'].shift(1) <= df['ema{suffix}'].shift(1))")
        elif r_type == 'rsi_below':
            w = params.get('window', 14)
            l = params.get('level', 30)
            calc_lines.append(f"df['rsi{suffix}'] = self.calculate_rsi(df['Close'], {w})")
            conditions.append(f"df['rsi{suffix}'] < {l}")
        elif r_type == 'rsi_cross':
            w = params.get('window', 14)
            l = params.get('level', 30)
            calc_lines.append(f"df['rsi{suffix}'] = self.calculate_rsi(df['Close'], {w})")
            conditions.append(f"(df['rsi{suffix}'] > {l}) & (df['rsi{suffix}'].shift(1) <= {l})")
        elif r_type == 'macd_cross':
            calc_lines.append(f"macd_l{suffix}, sig_l{suffix}, _ = self.calculate_macd(df['Close'])")
            calc_lines.append(f"df['macd_line{suffix}'] = macd_l{suffix}")
            calc_lines.append(f"df['macd_signal{suffix}'] = sig_l{suffix}")
            conditions.append(f"(df['macd_line{suffix}'] > df['macd_signal{suffix}']) & (df['macd_line{suffix}'].shift(1) <= df['macd_signal{suffix}'].shift(1))")
        elif r_type == 'macd_hist_cross':
            calc_lines.append(f"_, _, macd_h{suffix} = self.calculate_macd(df['Close'])")
            calc_lines.append(f"df['macd_hist{suffix}'] = macd_h{suffix}")
            conditions.append(f"(df['macd_hist{suffix}'] > 0) & (df['macd_hist{suffix}'].shift(1) <= 0)")
            
    calc_str = "\n        ".join(calc_lines)
    cond_str = " & ".join(conditions) if conditions else "False"
    
    template = f"""import pandas as pd
import numpy as np

class QuantMatrixStrategy:
    \"\"\"
    Production-ready Object-Oriented Trading Strategy Engine.
    \"\"\"
    def __init__(self, config: dict):
        self.config = config
        self.ticker = config.get('ticker', '{ticker}')
        self.holding_period = config.get('backtest_settings', {{}}).get('holding_period', 15)
        self.stop_loss = config.get('backtest_settings', {{}}).get('stop_loss_pct', -0.05)
        self.take_profit = config.get('backtest_settings', {{}}).get('take_profit_pct', 0.15)
        
    def calculate_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def calculate_macd(self, series: pd.Series, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
        fast_ema = series.ewm(span=fast_period, adjust=False).mean()
        slow_ema = series.ewm(span=slow_period, adjust=False).mean()
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        macd_hist = macd_line - signal_line
        return macd_line, signal_line, macd_hist

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        \"\"\"
        Precalculates technical indicators and evaluates the exact matched rules.
        \"\"\"
        # 1. Precalculate technical indicators
        {calc_str}
        
        # 2. Generate Buy Signals
        df['Buy_Signal'] = {cond_str}
        return df
        
    def extract_live_action(self, current_position: dict, latest_bar: dict) -> str:
        \"\"\"
        Evaluates the current position state against the newest bar data to command live execution.
        Returns: "BUY", "SELL", or "HOLD"
        \"\"\"
        # If no position is active, look for a new buy signal
        if current_position is None or not current_position.get('active', False):
            if latest_bar.get('Buy_Signal', False):
                return "BUY"
            return "HOLD"
            
        # If a position is active, evaluate exits
        entry_price = current_position.get('entry_price', 0.0)
        days_held = current_position.get('days_held', 0)
        current_price = latest_bar.get('Close', 0.0)
        
        if entry_price > 0:
            price_change = (current_price - entry_price) / entry_price
            if price_change <= self.stop_loss:
                return "SELL"
            elif price_change >= self.take_profit:
                return "SELL"
                
        if days_held >= self.holding_period:
            return "SELL"
            
        return "HOLD"

if __name__ == '__main__':
    # --- Example Usage ---
    import yfinance as yf
    
    print(f"Initializing OOP Strategy for {ticker}...")
    mock_config = {{
        'ticker': '{ticker}',
        'backtest_settings': {{
            'holding_period': 15,
            'stop_loss_pct': -0.05,
            'take_profit_pct': 0.15
        }}
    }}
    
    strategy = QuantMatrixStrategy(mock_config)
    
    df = yf.download(strategy.ticker, period="1y")
    if not df.empty:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        
        df = strategy.generate_signals(df)
        
        latest = df.iloc[-1].to_dict()
        action = strategy.extract_live_action({{'active': False}}, latest)
        print(f"Latest Live Action Command: {{action}}")
    else:
        print("No data retrieved for example.")
"""
    return template

def export_strategy_pack(ticker: str, strategy_config: dict) -> io.BytesIO:
    """
    Creates a zip archive in memory containing the Pine Script, Python backtester, and config.json.
    """
    pine_script = generate_pine_script(ticker, strategy_config)
    python_script = generate_python_script(ticker, strategy_config)
    
    # Extract clean technical rules
    clean_rules = []
    for r in strategy_config.get('rules', []):
        clean_rules.append({
            'indicator': r.get('type'),
            'parameters': r.get('params'),
            'description': r.get('name')
        })
        
    config_data = {
        'ticker': ticker,
        'strategy_name': strategy_config.get('name', 'Custom Match Strategy'),
        'version': '1.0.0',
        'rules': strategy_config.get('rules', []),
        'technical_bounds': clean_rules,
        'backtest_settings': {
            'holding_period': 15,
            'stop_loss_pct': -0.05,
            'take_profit_pct': 0.15
        }
    }
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr('strategy.pine', pine_script)
        zip_file.writestr('strategy.py', python_script)
        zip_file.writestr('config.json', json.dumps(config_data, indent=2))
        
    zip_buffer.seek(0)
    return zip_buffer


def generate_strategy_brief(strategy_data: dict, ticker: str) -> str:
    """
    Calls the Google Gemini API using the gemini-2.5-flash model to generate a crisp 2-bullet point
    summary of the strategy's performance and core theory.
    """
    global client
    if client is None:
        try:
            from google import genai
            client = genai.Client()
        except Exception:
            return ""

    try:
        # Extract rules descriptions
        rules_desc = ", ".join([r.get('name', '') for r in strategy_data.get('rules', [])])
        
        # Build raw backtest text
        prompt = (
            f"Ticker: {ticker}\n"
            f"Strategy Name: {strategy_data.get('name', 'Unknown')}\n"
            f"Rules: {rules_desc}\n"
            f"Win Rate: {strategy_data.get('win_rate', 0.0) * 100:.1f}%\n"
            f"Profit Factor: {strategy_data.get('profit_factor', 0.0):.2f}\n"
            f"Total Return: {strategy_data.get('total_return', 0.0) * 100:.2f}%\n"
            f"Total Trades: {strategy_data.get('total_trades', 0)}"
        )
        
        system_instruction = (
            "You are a elite quantitative trading terminal analyst. Review the provided backtest data "
            "for the given ticker. Generate a 2-bullet-point summary in plain English. "
            "Bullet 1: 'The Theory' (how this parameter combo works). "
            "Bullet 2: 'Performance Breakdown' (why it won or lost money based on its profit factor and win rate). "
            "Keep it under 50 words total. No jargon, no fluff, no markdown styling."
        )
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={
                'system_instruction': system_instruction
            }
        )
        return response.text.strip() if response.text else ""
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return ""
