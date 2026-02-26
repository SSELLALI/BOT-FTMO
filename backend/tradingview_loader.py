"""
TradingView CSV Data Loader

Loads OHLC data exported from TradingView Pro.
Format: time (UNIX timestamp), open, high, low, close, [indicators...]
"""
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict

import pandas as pd

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "historical_data")


def load_tradingview_csv(csv_path: str, max_candles: int = None) -> List[Dict]:
    """Load TradingView CSV into candle dicts for the backtester."""
    if not os.path.exists(csv_path):
        logger.error(f"File not found: {csv_path}")
        return []

    df = pd.read_csv(csv_path)

    # TradingView format: time is UNIX timestamp
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)

    # Keep only OHLC
    required = ["open", "high", "low", "close"]
    for col in required:
        if col not in df.columns:
            logger.error(f"Missing column: {col} in {csv_path}")
            return []

    df = df.dropna(subset=required)
    df = df.sort_values("datetime").reset_index(drop=True)

    candles = []
    for _, row in df.iterrows():
        candles.append({
            "datetime": row["datetime"].to_pydatetime(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": 0,
        })

    if max_candles and len(candles) > max_candles:
        candles = candles[-max_candles:]

    logger.info(f"Loaded {len(candles)} candles from TradingView CSV: {csv_path}")
    if candles:
        logger.info(f"  Period: {candles[0]['datetime']} -> {candles[-1]['datetime']}")

    return candles
