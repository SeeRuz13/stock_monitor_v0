"""
Algoritmo di trend detection - PUNTO DI PLUGIN.

Per sostituirlo con il tuo algoritmo: riscrivi il corpo di detect_trend()
mantenendo la stessa firma (input/output) cosi' monitor.py non richiede modifiche.

Input:
    history: pandas.DataFrame con almeno una colonna 'Close', indicizzato per data,
              ordinato dal piu' vecchio al piu' recente.
    params:   dict letto da config.json -> "trend_algorithm"

Output: dict con chiavi:
    signal: "up" | "down" | "none"
    value:  ultimo valore della derivata filtrata, in % al giorno
"""

import pandas as pd


def detect_trend(history: pd.DataFrame, params: dict) -> dict:
    window = params.get("smoothing_window", 5)
    rise_threshold = params.get("rise_threshold_pct_per_day", 0.5)
    fall_threshold = params.get("fall_threshold_pct_per_day", -0.5)

    if len(history) < window + 2:
        return {"signal": "none", "value": 0.0}

    close = history["Close"]

    # 1. Filtra il rumore: media mobile esponenziale
    smoothed = close.ewm(span=window, adjust=False).mean()

    # 2. Derivata: variazione percentuale giorno su giorno della serie filtrata
    derivative_pct = smoothed.pct_change() * 100

    # 3. Ultimo valore della derivata filtrata (di nuovo smussata per stabilita')
    filtered_derivative = derivative_pct.ewm(span=window, adjust=False).mean()
    latest_value = float(filtered_derivative.iloc[-1])

    if latest_value >= rise_threshold:
        signal = "up"
    elif latest_value <= fall_threshold:
        signal = "down"
    else:
        signal = "none"

    return {"signal": signal, "value": round(latest_value, 3)}
