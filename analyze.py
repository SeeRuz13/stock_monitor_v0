"""
Analisi tecnica su richiesta di un singolo titolo/indice.

    python analyze.py ^GSPC

Descrive lo stato attuale (non fa previsioni): trend (medie mobili, ADX),
momentum (RSI), volatilita' (ATR), performance, supporti/resistenze da pivot
settimanali, ritracciamenti di Fibonacci sugli ultimi swing principali.
Stampa un riepilogo e salva docs/analysis/<ticker>.json.

Su GitHub: Actions -> Analisi -> Run workflow (campo ticker).
"""

import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from common import DOCS_DIR, download_history, save_json
from indicators import atr, rsi, sma

FIB_RATIOS = [0.236, 0.382, 0.5, 0.618, 0.786]


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up = df["High"].diff()
    down = -df["Low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = atr(df, 1)  # true range non smussato (alpha=1)
    atr_s = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_s
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_s
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / period, adjust=False).mean(), plus_di, minus_di


def pivots(df: pd.DataFrame, window: int):
    """Massimi/minimi locali confermati: (data, prezzo)."""
    hi = df["High"].rolling(2 * window + 1, center=True).max()
    lo = df["Low"].rolling(2 * window + 1, center=True).min()
    highs = [(d, float(p)) for d, p, m in zip(df.index, df["High"], hi) if p == m]
    lows = [(d, float(p)) for d, p, m in zip(df.index, df["Low"], lo) if p == m]
    return highs, lows


def zones(points, tolerance_pct: float):
    pts = sorted(points, key=lambda x: x[1])
    groups, cur = [], []
    for d, p in pts:
        if cur and abs(p / np.mean([q for _, q in cur]) - 1) * 100 > tolerance_pct:
            groups.append(cur)
            cur = []
        cur.append((d, p))
    if cur:
        groups.append(cur)
    return [
        {"price": round(float(np.mean([p for _, p in g])), 2), "touches": len(g),
         "last": max(d for d, _ in g).date().isoformat()}
        for g in groups
    ]


def fib(low: float, high: float, uptrend: bool) -> dict:
    span = high - low
    if uptrend:  # ritracciamenti di una salita: livelli sotto il massimo
        return {str(r): round(high - span * r, 2) for r in FIB_RATIOS}
    return {str(r): round(low + span * r, 2) for r in FIB_RATIOS}


def swing(df: pd.DataFrame, lookback_days: int):
    """Swing principale nel periodo: minimo e massimo, e quale viene dopo."""
    d = df.iloc[-lookback_days:]
    lo_d, hi_d = d["Low"].idxmin(), d["High"].idxmax()
    low, high = float(d["Low"].min()), float(d["High"].max())
    uptrend = hi_d > lo_d
    return {"lookback_days": lookback_days, "low": round(low, 2), "low_date": lo_d.date().isoformat(),
            "high": round(high, 2), "high_date": hi_d.date().isoformat(),
            "direction": "salita" if uptrend else "discesa", "levels": fib(low, high, uptrend)}


def perf(close: pd.Series, days: int):
    return round(float(close.iloc[-1] / close.iloc[-days - 1] - 1) * 100, 2) if len(close) > days else None


def analyze(ticker: str) -> dict:
    data = download_history([ticker], "5y")
    if ticker not in data:
        raise SystemExit(f"Nessun dato per {ticker}")
    df = data[ticker]
    c = df["Close"]
    last = float(c.iloc[-1])
    s20, s50, s200 = sma(c, 20), sma(c, 50), sma(c, 200)
    adx_s, pdi, mdi = adx(df)
    a = atr(df, 14)

    weekly = df.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    wh, wl = pivots(weekly.iloc[-104:], 3)
    all_zones = [z for z in zones(wh + wl, 1.5) if z["touches"] >= 2]
    supports = sorted([z for z in all_zones if z["price"] < last], key=lambda z: -z["price"])[:4]
    resistances = sorted([z for z in all_zones if z["price"] > last], key=lambda z: z["price"])[:4]

    year = c[c.index.year == c.index[-1].year]
    out = {
        "ticker": ticker,
        "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "date": c.index[-1].date().isoformat(),
        "close": round(last, 2),
        "sma20": round(float(s20.iloc[-1]), 2),
        "sma50": round(float(s50.iloc[-1]), 2),
        "sma200": round(float(s200.iloc[-1]), 2),
        "vs_sma50_pct": round((last / s50.iloc[-1] - 1) * 100, 2),
        "vs_sma200_pct": round((last / s200.iloc[-1] - 1) * 100, 2),
        "sma200_slope_1m_pct": round((s200.iloc[-1] / s200.iloc[-22] - 1) * 100, 2),
        "golden_cross": bool(s50.iloc[-1] > s200.iloc[-1]),
        "adx": round(float(adx_s.iloc[-1]), 1),
        "plus_di": round(float(pdi.iloc[-1]), 1),
        "minus_di": round(float(mdi.iloc[-1]), 1),
        "rsi14": round(float(rsi(c, 14).iloc[-1]), 1),
        "atr14_pct": round(float(a.iloc[-1] / last * 100), 2),
        "high_52w": round(float(df["High"].iloc[-252:].max()), 2),
        "low_52w": round(float(df["Low"].iloc[-252:].min()), 2),
        "from_high_52w_pct": round((last / df["High"].iloc[-252:].max() - 1) * 100, 2),
        "all_time_high_5y": round(float(df["High"].max()), 2),
        "perf_pct": {"1m": perf(c, 21), "3m": perf(c, 63), "6m": perf(c, 126), "1y": perf(c, 252),
                     "ytd": round(float(last / year.iloc[0] - 1) * 100, 2) if len(year) > 1 else None},
        "supports": supports,
        "resistances": resistances,
        "fib_6m": swing(df, 126),
        "fib_1y": swing(df, 252),
        "fib_2y": swing(df, 504),
        "last_20_closes": [round(float(x), 2) for x in c.iloc[-20:]],
    }
    return out


def main():
    ticker = (sys.argv[1] if len(sys.argv) > 1 else "^GSPC").strip()
    res = analyze(ticker)
    os.makedirs(os.path.join(DOCS_DIR, "analysis"), exist_ok=True)
    safe = ticker.replace("^", "").replace("/", "_")
    save_json(os.path.join(DOCS_DIR, "analysis", f"{safe}.json"), res)
    for k, v in res.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
