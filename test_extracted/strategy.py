import pandas as pd
import numpy as np
import yfinance as yf

# Backtest parameters
TICKER = "SPY"
HOLDING_PERIOD = 15
STOP_LOSS = -0.05
TAKE_PROFIT = 0.15

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
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

def run_strategy():
    print(f"Fetching 2 years of daily data for {TICKER}...")
    df = yf.download(TICKER, period="2y")
    if df.empty:
        print("Error: No data retrieved.")
        return
        
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    df = df.reset_index()
    df['DateStr'] = df['Date'].dt.strftime('%Y-%m-%d')
    
    # 1. Precalculate technical indicators
    df['ema_0'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['rsi_1'] = calculate_rsi(df['Close'], 14)
    
    # 2. Generate Buy Signals
    df['Buy_Signal'] = (df['Close'] > df['ema_0']) & (df['Close'].shift(1) <= df['ema_0'].shift(1)) & (df['rsi_1'] > 30) & (df['rsi_1'].shift(1) <= 30)
    
    # 3. Simulate Trades using single-position State-Machine
    close = df['Close'].values
    dates = df['DateStr'].values
    n = len(df)
    
    position_active = False
    entry_idx = -1
    entry_price = 0.0
    
    trades = []
    
    for i in range(n):
        if not position_active:
            if df['Buy_Signal'].iloc[i]:
                position_active = True
                entry_idx = i
                entry_price = close[i]
        else:
            current_price = close[i]
            price_change = (current_price - entry_price) / entry_price
            days_held = i - entry_idx
            
            if price_change <= STOP_LOSS:
                trades.append((dates[entry_idx], dates[i], entry_price, current_price, price_change, 'Stop Loss'))
                position_active = False
            elif price_change >= TAKE_PROFIT:
                trades.append((dates[entry_idx], dates[i], entry_price, current_price, price_change, 'Take Profit'))
                position_active = False
            elif days_held >= HOLDING_PERIOD:
                trades.append((dates[entry_idx], dates[i], entry_price, current_price, price_change, 'Holding Period'))
                position_active = False
                
    if position_active:
        trades.append((dates[entry_idx], dates[-1], entry_price, close[-1], (close[-1] - entry_price) / entry_price, 'End of Data'))
        
    trades_df = pd.DataFrame(trades, columns=['Entry_Date', 'Exit_Date', 'Entry_Price', 'Exit_Price', 'Return', 'Exit_Reason'])
    
    print("\n" + "="*50)
    print("                REVERSE-ENGINEERED STRATEGY LOG")
    print("="*50)
    print(trades_df.to_string(index=False))
    
    if not trades_df.empty:
        win_rate = (trades_df['Return'] > 0).mean()
        total_return = (trades_df['Return'] + 1).prod() - 1.0
        print("\n" + "-"*50)
        print(f"Total Trades:  {len(trades_df)}")
        print(f"Win Rate:      {win_rate:.2%}")
        print(f"Total Return:  {total_return:.2%}")
        print("-"*50)
    else:
        print("\nNo trades executed during the period.")

if __name__ == '__main__':
    run_strategy()
