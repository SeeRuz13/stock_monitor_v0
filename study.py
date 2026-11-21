"""
Studio storico di breve periodo sull'S&P 500 (orizzonte 1-10 sedute).

1. "Situazioni simili a oggi": cosa e' successo nei giorni successivi quando
   l'indice era in condizioni tecniche simili (distanza dal massimo, posizione
   rispetto alle medie, calo degli ultimi 3 giorni, VIX). Un episodio = primo
   giorno di un gruppo di segnali ravvicinati (i giorni consecutivi non vengono
   contati piu' volte).
2. Trimestrali Nvidia: movimento di NVDA e S&P nella seduta dopo i conti.
3. Settimana del Thanksgiving: rendimento storico.

Tutto descrittivo: frequenze passate, non previsioni.
    python study.py
"""

import os
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from common import DOCS_DIR, download_history, save_json
from indicators import rsi, sma

HORIZONS = [1, 2, 3, 5, 10, 20, 60, 120, 250]


def forward_stats(close: pd.Series, idx: list) -> dict:
    out = {"episodes": len(idx)}
    if not idx:
        return out
    arr = close.to_numpy()
    for h in HORIZONS:
        rets = [(arr[i + h] / arr[i] - 1) * 100 for i in idx if i + h < len(arr)]
        if not rets:
            continue
        r = np.array(rets)
        out[f"{h}d"] = {
            "n": len(r), "mean": round(float(r.mean()), 2), "median": round(float(np.median(r)), 2),
            "pct_up": round(float((r > 0).mean() * 100), 1),
            "p10": round(float(np.percentile(r, 10)), 2), "p90": round(float(np.percentile(r, 90)), 2),
            "min": round(float(r.min()), 2), "max": round(float(r.max()), 2),
        }
    # escursioni entro 5 sedute (sulle chiusure)
    down2 = up25 = n = 0
    for i in idx:
        if i + 5 >= len(arr):
            continue
        window = arr[i + 1 : i + 6] / arr[i] - 1
        n += 1
        down2 += window.min() <= -0.02
        up25 += window.max() >= 0.025
    if n:
        out["within_5d"] = {"touch_minus_2pct": round(down2 / n * 100, 1), "touch_plus_2_5pct": round(up25 / n * 100, 1)}
    # quanto e' sceso ancora dopo il segnale (minimo entro 60 sedute) e quante
    # volte e' diventato un mercato ribassista (-20% dal massimo a 1 anno) entro 250 sedute
    further, bear, n2 = [], 0, 0
    for i in idx:
        if i + 60 < len(arr):
            further.append((arr[i + 1 : i + 61].min() / arr[i] - 1) * 100)
        if i + 250 < len(arr) and i >= 252:
            n2 += 1
            prior_high = arr[i - 251 : i + 1].max()
            bear += arr[i + 1 : i + 251].min() <= prior_high * 0.8
    if further:
        f = np.array(further)
        out["further_drop_60d"] = {"median": round(float(np.median(f)), 2), "p10": round(float(np.percentile(f, 10)), 2),
                                   "pct_no_new_low_beyond_3pct": round(float((f > -3).mean() * 100), 1)}
    if n2:
        out["became_bear_within_1y_pct"] = round(bear / n2 * 100, 1)
    return out


def episodes(mask: pd.Series, gap: int = 10) -> list:
    idx, last = [], -10**9
    for i, v in enumerate(mask.to_numpy()):
        if v and i - last > gap:
            idx.append(i)
        if v:
            last = i
    return idx


def similar_situations(spx: pd.DataFrame, vix: pd.DataFrame) -> dict:
    c = spx["Close"]
    c = c[c.index >= "1950-01-01"]
    s50, s200 = sma(c, 50), sma(c, 200)
    dd = (c / c.rolling(252, min_periods=200).max() - 1) * 100
    r3 = (c / c.shift(3) - 1) * 100
    vs200 = (c / s200 - 1) * 100

    a = (dd <= -3) & (dd >= -8) & (c > s200) & (c < s50)
    b = a & (r3 <= -2)
    cc = b & (vs200 <= 3)
    v = vix["Close"].reindex(c.index)
    d = b & (v >= 20) & (v <= 30)
    r14 = rsi(c, 14)
    r5 = (c / c.shift(5) - 1) * 100
    s200_up = s200 > s200.shift(21)
    # situazione di oggi (fine novembre 2026): -12% dal massimo, sotto la media 200 ancora in salita, RSI ~25, VIX ~36
    e = (dd <= -9) & (dd >= -16) & (c < s200) & s200_up & (r14 < 32)
    f = e & (v > 28)
    g = (dd <= -9) & (dd >= -16) & (r5 <= -5)

    today = {
        "date": c.index[-1].date().isoformat(), "close": round(float(c.iloc[-1]), 2),
        "from_high_pct": round(float(dd.iloc[-1]), 2), "vs_sma200_pct": round(float(vs200.iloc[-1]), 2),
        "below_sma50": bool(c.iloc[-1] < s50.iloc[-1]), "ret_3d_pct": round(float(r3.iloc[-1]), 2),
        "vix": round(float(v.iloc[-1]), 2) if pd.notna(v.iloc[-1]) else None,
        "rsi14": round(float(r14.iloc[-1]), 1), "ret_5d_pct": round(float(r5.iloc[-1]), 2),
        "sma200_rising": bool(s200_up.iloc[-1]),
    }
    # esclude oggi stesso dai campioni
    hist = slice(0, len(c) - 1)
    def ep(mask):
        return [i for i in episodes(mask.iloc[hist])]
    return {
        "today": today,
        "baseline_all_days": forward_stats(c, list(range(200, len(c) - 1))),
        "A_3_8pct_from_high_above_sma200_below_sma50": forward_stats(c, ep(a)),
        "B_A_plus_3day_drop_2pct": forward_stats(c, ep(b)),
        "C_B_plus_within_3pct_of_sma200": forward_stats(c, ep(cc)),
        "D_B_plus_vix_20_30_since_1990": forward_stats(c, ep(d)),
        "E_9_16pct_from_high_below_rising_sma200_rsi_lt_32": forward_stats(c, ep(e)),
        "F_E_plus_vix_gt_28_since_1990": forward_stats(c, ep(f)),
        "G_9_16pct_from_high_5day_drop_5pct": forward_stats(c, ep(g)),
        "B_episode_dates_last_15": [c.index[i].date().isoformat() for i in ep(b)][-15:],
        "E_episode_dates": [c.index[i].date().isoformat() for i in ep(e)],
        "F_episode_dates": [c.index[i].date().isoformat() for i in ep(f)],
        "G_episode_dates": [c.index[i].date().isoformat() for i in ep(g)],
    }


def nvidia_earnings(spx: pd.DataFrame) -> dict:
    import yfinance as yf

    try:
        ed = yf.Ticker("NVDA").get_earnings_dates(limit=60)
    except Exception as exc:
        return {"error": str(exc)}
    if ed is None or len(ed) == 0:
        return {"error": "nessuna data"}
    nvda = download_history(["NVDA"], "max")["NVDA"]["Close"]
    s = spx["Close"]
    rows = []
    for ts in ed.index:
        d = pd.Timestamp(ts).tz_localize(None).normalize() if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).normalize()
        if d >= pd.Timestamp(date.today()):
            continue
        # NVDA pubblica dopo la chiusura: reazione = seduta successiva
        pos = nvda.index.searchsorted(d, side="right") - 1
        if pos < 0 or pos + 3 >= len(nvda) or nvda.index[pos].normalize() != d:
            continue
        sp = s.index.searchsorted(nvda.index[pos])
        if sp + 3 >= len(s):
            continue
        rows.append({
            "date": d.date().isoformat(),
            "nvda_next_day": round(float(nvda.iloc[pos + 1] / nvda.iloc[pos] - 1) * 100, 2),
            "spx_next_day": round(float(s.iloc[sp + 1] / s.iloc[sp] - 1) * 100, 2),
            "spx_3d": round(float(s.iloc[sp + 3] / s.iloc[sp] - 1) * 100, 2),
        })
    if not rows:
        return {"error": "nessuna corrispondenza"}
    df = pd.DataFrame(rows)
    summ = {}
    for col in ("nvda_next_day", "spx_next_day", "spx_3d"):
        x = df[col]
        summ[col] = {"mean": round(float(x.mean()), 2), "median": round(float(x.median()), 2),
                     "mean_abs": round(float(x.abs().mean()), 2), "pct_up": round(float((x > 0).mean() * 100), 1),
                     "min": float(x.min()), "max": float(x.max())}
    return {"n": len(df), "summary": summ, "events": rows[:20]}


def thanksgiving_weeks(spx: pd.DataFrame) -> dict:
    s = spx["Close"]
    rows = []
    for y in range(1950, date.today().year):
        nov1 = date(y, 11, 1)
        first_thu = nov1 + timedelta(days=(3 - nov1.weekday()) % 7)
        tg = pd.Timestamp(first_thu + timedelta(weeks=3))
        start = s[s.index <= tg - pd.Timedelta(days=4)]  # chiusura venerdi' precedente
        end = s[s.index <= tg + pd.Timedelta(days=1)]    # chiusura venerdi' dopo
        if len(start) == 0 or len(end) == 0:
            continue
        rows.append(round(float(end.iloc[-1] / start.iloc[-1] - 1) * 100, 2))
    r = np.array(rows)
    return {"years": len(r), "mean": round(float(r.mean()), 2), "median": round(float(np.median(r)), 2),
            "pct_up": round(float((r > 0).mean() * 100), 1), "min": float(r.min()), "max": float(r.max())}


def main():
    data = download_history(["^GSPC", "^VIX"], "max")
    spx, vix = data["^GSPC"], data["^VIX"]
    res = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "similar_situations": similar_situations(spx, vix),
        "nvidia_earnings": nvidia_earnings(spx),
        "thanksgiving_week": thanksgiving_weeks(spx),
    }
    os.makedirs(os.path.join(DOCS_DIR, "analysis"), exist_ok=True)
    save_json(os.path.join(DOCS_DIR, "analysis", "study_short_term.json"), res)
    import json
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
