from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import pandas as pd

from engine import get_chart_data, sweep_strategies, export_strategy_pack

app = FastAPI(title="CLKR Pattern Matching Heuristic Engine API")

# Enable CORS for frontend development server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://clkr-ten.vercel.app",
        "http://localhost:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChartResponseItem(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float

class AnalyzeRequest(BaseModel):
    ticker: str
    pins: List[str]

class ExportRequest(BaseModel):
    ticker: str
    strategy: Dict[str, Any]

@app.get("/api/chart", response_model=List[ChartResponseItem])
def get_chart(ticker: str):
    if not ticker:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ticker parameter is required"
        )
        
    df = get_chart_data(ticker)
    if df is None or df.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No stock data found for ticker '{ticker}'"
        )
        
    chart_items = []
    for _, row in df.iterrows():
        # Handle cases where yfinance returned NaN value
        try:
            chart_items.append(ChartResponseItem(
                time=str(row['DateStr']),
                open=float(row['Open']),
                high=float(row['High']),
                low=float(row['Low']),
                close=float(row['Close']),
                volume=float(row['Volume'])
            ))
        except (ValueError, TypeError):
            continue
            
    return chart_items

@app.post("/api/analyze")
def analyze_pins(payload: AnalyzeRequest):
    ticker = payload.ticker.strip().upper()
    pins = payload.pins
    
    if not ticker:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ticker is required"
        )
    if not pins:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one click pin is required for pattern reverse engineering"
        )
        
    df = get_chart_data(ticker)
    if df is None or df.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Could not load data for ticker '{ticker}'"
        )
        
    try:
        top_strategies = sweep_strategies(df, pins)
        return {
            "ticker": ticker,
            "strategies": top_strategies
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error executing strategy sweep: {str(e)}"
        )

@app.post("/api/export")
def export_pack(payload: ExportRequest):
    ticker = payload.ticker.strip().upper()
    strategy = payload.strategy
    
    if not ticker or not strategy:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ticker and strategy configuration are required"
        )
        
    try:
        zip_buffer = export_strategy_pack(ticker, strategy)
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={ticker.lower()}_strategy_pack.zip"
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate strategy pack zip: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
