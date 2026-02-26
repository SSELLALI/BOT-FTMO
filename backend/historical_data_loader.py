"""
Real Historical Data Loader for FTMO Backtesting
Downloads and caches real EURUSD data from Yahoo Finance
"""
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional

import pandas as pd

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "historical_data")


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def download_and_cache(symbol: str = "EURUSD") -> Tuple[str, str]:
    """Download real forex data and cache as CSV. Returns (h1_path, m15_path)."""
    ensure_data_dir()
    ticker = f"{symbol}=X"
    h1_path = os.path.join(DATA_DIR, f"{symbol}_H1.csv")
    m15_path = os.path.join(DATA_DIR, f"{symbol}_M15.csv")

    try:
        import yfinance as yf

        # H1: up to 2 years
        if not os.path.exists(h1_path) or _file_age_hours(h1_path) > 24:
            logger.info(f"Downloading {symbol} H1 data...")
            h1 = yf.download(ticker, period="2y", interval="1h", progress=False)
            if len(h1) > 0:
                h1.to_csv(h1_path)
                logger.info(f"Saved {len(h1)} H1 candles to {h1_path}")

        # M15: up to 60 days
        if not os.path.exists(m15_path) or _file_age_hours(m15_path) > 24:
            logger.info(f"Downloading {symbol} M15 data...")
            m15 = yf.download(ticker, period="60d", interval="15m", progress=False)
            if len(m15) > 0:
                m15.to_csv(m15_path)
                logger.info(f"Saved {len(m15)} M15 candles to {m15_path}")

    except Exception as e:
        logger.error(f"Failed to download data: {e}")

    return h1_path, m15_path


def _file_age_hours(path: str) -> float:
    if not os.path.exists(path):
        return 999
    mtime = os.path.getmtime(path)
    return (datetime.now().timestamp() - mtime) / 3600


def load_candles_from_csv(csv_path: str, max_candles: int = None) -> List[Dict]:
    """Load candle data from CSV file into the format expected by strategies."""
    if not os.path.exists(csv_path):
        logger.warning(f"CSV not found: {csv_path}")
        return []

    try:
        df = pd.read_csv(csv_path, parse_dates=True)

        # Handle multi-level columns from yfinance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Find datetime column (first column or 'Datetime' or 'Date')
        date_col = None
        for col in df.columns:
            if col.lower() in ("datetime", "date", "timestamp"):
                date_col = col
                break
        if date_col is None:
            date_col = df.columns[0]

        df[date_col] = pd.to_datetime(df[date_col], utc=True)
        df = df.set_index(date_col)

        # Normalize column names
        col_map = {}
        for col in df.columns:
            lower = col.lower().strip()
            if "close" in lower:
                col_map[col] = "close"
            elif "high" in lower:
                col_map[col] = "high"
            elif "low" in lower:
                col_map[col] = "low"
            elif "open" in lower:
                col_map[col] = "open"
            elif "volume" in lower:
                col_map[col] = "volume"
        df = df.rename(columns=col_map)

        required = ["open", "high", "low", "close"]
        for col in required:
            if col not in df.columns:
                logger.error(f"Missing column: {col}")
                return []

        # Remove NaN rows
        df = df.dropna(subset=required)

        # Convert to list of dicts
        candles = []
        for idx, row in df.iterrows():
            dt = idx
            if hasattr(dt, 'to_pydatetime'):
                dt = dt.to_pydatetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            candles.append({
                "datetime": dt,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row.get("volume", 100))
            })

        if max_candles and len(candles) > max_candles:
            candles = candles[-max_candles:]

        logger.info(f"Loaded {len(candles)} candles from {csv_path}")
        return candles

    except Exception as e:
        logger.error(f"Failed to load CSV {csv_path}: {e}")
        return []


def get_real_data(symbol: str = "EURUSD", days: int = 60) -> Tuple[List[Dict], List[Dict]]:
    """
    Get real historical candle data for backtesting.
    Returns (h1_candles, m15_candles).
    Falls back to empty lists if data unavailable.
    """
    h1_path, m15_path = download_and_cache(symbol)

    h1_candles = load_candles_from_csv(h1_path)
    m15_candles = load_candles_from_csv(m15_path)

    # Filter by requested days
    if days and m15_candles:
        cutoff = m15_candles[-1]["datetime"] - pd.Timedelta(days=days)
        m15_candles = [c for c in m15_candles if c["datetime"] >= cutoff]

    if days and h1_candles:
        # H1 needs more history for EMA200, so keep at least 300 extra candles
        cutoff = h1_candles[-1]["datetime"] - pd.Timedelta(days=days + 30)
        h1_candles = [c for c in h1_candles if c["datetime"] >= cutoff]

    logger.info(f"Real data: {len(h1_candles)} H1 candles, {len(m15_candles)} M15 candles")
    return h1_candles, m15_candles
