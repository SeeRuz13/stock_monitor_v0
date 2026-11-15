"""
Indicatori tecnici di base, tutti su DataFrame con colonne Open/High/Low/Close/Volume.
"""

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def rsi(close: pd.Series, period: int) -> pd.Series:
    """RSI di Wilder (0-100)."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0)


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Average True Range: escursione media giornaliera, in unita' di prezzo."""
    prev_close = df["Close"].shift()
    tr = pd.concat(
        [df["High"] - df["Low"], (df["High"] - prev_close).abs(), (df["Low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def drawdown_from_high(close: pd.Series, window: int) -> pd.Series:
    """Distanza % (<= 0) dal massimo delle ultime `window` sedute."""
    rolling_max = close.rolling(window, min_periods=1).max()
    return (close / rolling_max - 1) * 100
