"""
Algoritmo di trend detection - PUNTO DI PLUGIN.

Per sostituirlo con il tuo algoritmo: riscrivi il corpo di detect_trend()
mantenendo la stessa firma (input/output) cosi' monitor.py non richiede modifiche.

Input:
    history: pandas.DataFrame con colonne 'High', 'Low', 'Close', indicizzato per
              data, ordinato dal piu' vecchio al piu' recente.
    params:   dict letto da config.json -> "trend_algorithm"

Output: dict con chiavi:
    signal: "up" | "down" | "none"
    value:  istogramma MACD (macd - signal) dell'ultimo giorno
    adx:    forza del trend (0-100), per contesto nei messaggi di alert

Logica: incrocio MACD/signal per la direzione, filtrato dall'ADX per scartare
i segnali quando il mercato e' laterale (nessun trend abbastanza forte dietro).
"""

import numpy as np
import pandas as pd


def _macd(close: pd.Series, fast: int, slow: int, signal_span: int):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=signal_span, adjust=False).mean()
    return macd, signal


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int):
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    true_range = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = true_range.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=close.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=close.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx, plus_di, minus_di


def detect_trend(history: pd.DataFrame, params: dict) -> dict:
    fast = params.get("macd_fast", 12)
    slow = params.get("macd_slow", 26)
    signal_span = params.get("macd_signal", 9)
    adx_period = params.get("adx_period", 14)
    adx_threshold = params.get("adx_threshold", 25)

    if len(history) < slow + signal_span:
        return {"signal": "none", "value": 0.0, "adx": 0.0}

    close = history["Close"]
    macd, macd_signal = _macd(close, fast, slow, signal_span)
    adx, plus_di, minus_di = _adx(history["High"], history["Low"], close, adx_period)

    histogram = float((macd - macd_signal).iloc[-1])
    latest_adx = float(adx.iloc[-1])
    latest_macd = float(macd.iloc[-1])
    latest_macd_signal = float(macd_signal.iloc[-1])

    if latest_adx < adx_threshold:
        signal = "none"
    elif latest_macd > latest_macd_signal:
        signal = "up"
    elif latest_macd < latest_macd_signal:
        signal = "down"
    else:
        signal = "none"

    return {"signal": signal, "value": round(histogram, 3), "adx": round(latest_adx, 1)}
