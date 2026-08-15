"""
Algoritmo di supporti/resistenze + Fibonacci - PUNTO DI PLUGIN.

Firma diversa da detect_trend(history, params): qui servono anche current_price
(supporto/resistenza non hanno senso senza un prezzo di riferimento live) e
previous_signal (necessario per l'isteresi anti-flap, vedi sotto). monitor.py
gestisce questa differenza esplicitamente, non e' un'incoerenza.

Input:
    history:         pandas.DataFrame con colonne 'High', 'Low', 'Close', ordinato
                      dal piu' vecchio al piu' recente (storico piu' lungo di quello
                      usato per il trend: serve un lookback maggiore per pivot/
                      Fibonacci significativi).
    params:           dict letto da config.json -> "levels_algorithm"
    current_price:    ultimo prezzo live del titolo
    previous_signal:  segnale della run precedente (entry_state["last_level_signal"]),
                      usato per l'isteresi sulla soglia di "vicinanza"

Output: dict con chiavi:
    signal:              "none" | "near_support" | "near_resistance" |
                          "breakout_resistance" | "breakdown_support"
    value:                distanza % con segno dal livello che ha determinato il segnale
    level_price:          prezzo del livello, o None
    level_type:           "pivot" | "fibonacci" | None
    level_label:          descrizione leggibile (es. "pivot (3 tocchi)")
    touches:              numero di tocchi (solo per livelli pivot), o None
    confluence:           True se una zona pivot e un livello Fibonacci coincidono
    nearest_support:      {"price": ..., "touches": ...} | None
    nearest_resistance:   {"price": ..., "touches": ...} | None
    fib_levels:           dict ratio -> prezzo, o None
    fib_direction:        "uptrend" | "downtrend" | None

Logica: pivot (massimi/minimi locali confermati) -> clustering in zone di
supporto/resistenza per tocchi; stessi pivot usati per lo swing Fibonacci piu'
recente. Segnale di "rottura" ha priorita' su "vicinanza"; isteresi sulla soglia
di vicinanza per non generare alert ad ogni run mentre il prezzo oscilla al
margine della soglia.
"""

import pandas as pd


def _find_pivots(history: pd.DataFrame, window: int):
    highs, lows = history["High"], history["Low"]
    roll_max = highs.rolling(window=2 * window + 1, center=True, min_periods=2 * window + 1).max()
    roll_min = lows.rolling(window=2 * window + 1, center=True, min_periods=2 * window + 1).min()
    is_high = highs == roll_max
    is_low = lows == roll_min
    pivot_highs = [(i, float(highs.iloc[i])) for i in range(len(history)) if bool(is_high.iloc[i])]
    pivot_lows = [(i, float(lows.iloc[i])) for i in range(len(history)) if bool(is_low.iloc[i])]
    return pivot_highs, pivot_lows


def _cluster_zones(pivots, tolerance_pct: float):
    if not pivots:
        return []
    sorted_pivots = sorted(pivots, key=lambda p: p[1])
    clusters = []
    current = [sorted_pivots[0]]
    for pos, price in sorted_pivots[1:]:
        cluster_mean = sum(p for _, p in current) / len(current)
        if abs(price - cluster_mean) / cluster_mean * 100 <= tolerance_pct:
            current.append((pos, price))
        else:
            clusters.append(current)
            current = [(pos, price)]
    clusters.append(current)

    zones = []
    for c in clusters:
        prices = [p for _, p in c]
        zones.append(
            {
                "price": round(sum(prices) / len(prices), 4),
                "touches": len(c),
                "last_index": max(pos for pos, _ in c),
            }
        )
    return zones


def _fibonacci_levels(pivot_highs, pivot_lows, total_len: int, fib_lookback_bars: int):
    cutoff = max(0, total_len - fib_lookback_bars)
    recent_highs = [p for p in pivot_highs if p[0] >= cutoff]
    recent_lows = [p for p in pivot_lows if p[0] >= cutoff]
    if not recent_highs or not recent_lows:
        recent_highs, recent_lows = pivot_highs, pivot_lows
    if not recent_highs or not recent_lows:
        return None

    swing_high_pos, swing_high_price = max(recent_highs, key=lambda p: p[1])
    swing_low_pos, swing_low_price = min(recent_lows, key=lambda p: p[1])
    if swing_high_price <= swing_low_price:
        return None

    diff = swing_high_price - swing_low_price
    ratios = [0.236, 0.382, 0.5, 0.618, 0.786]

    if swing_high_pos > swing_low_pos:
        direction = "uptrend"
        levels = {str(r): round(swing_high_price - diff * r, 4) for r in ratios}
    else:
        direction = "downtrend"
        levels = {str(r): round(swing_low_price + diff * r, 4) for r in ratios}

    return {
        "direction": direction,
        "levels": levels,
        "swing_high": swing_high_price,
        "swing_low": swing_low_price,
    }


def _empty_result():
    return {
        "signal": "none",
        "value": 0.0,
        "level_price": None,
        "level_type": None,
        "level_label": "",
        "touches": None,
        "confluence": False,
        "nearest_support": None,
        "nearest_resistance": None,
        "fib_levels": None,
        "fib_direction": None,
    }


def detect_levels(history: pd.DataFrame, params: dict, current_price: float, previous_signal: str = "none") -> dict:
    window = params.get("pivot_window", 5)
    tolerance_pct = params.get("cluster_tolerance_pct", 1.5)
    min_touches = params.get("min_touches", 2)
    max_zones = params.get("max_zones", 3)
    proximity_pct = params.get("proximity_pct", 1.0)
    hysteresis_factor = params.get("hysteresis_factor", 1.5)
    fib_lookback_bars = params.get("fib_lookback_bars", 60)

    if len(history) < 2 * window + 1 or current_price is None:
        return _empty_result()

    pivot_highs, pivot_lows = _find_pivots(history, window)

    zones = _cluster_zones(pivot_highs + pivot_lows, tolerance_pct)
    qualified = [z for z in zones if z["touches"] >= min_touches]
    qualified.sort(key=lambda z: (-z["touches"], -z["last_index"]))

    supports = sorted([z for z in qualified if z["price"] < current_price], key=lambda z: -z["price"])[:max_zones]
    resistances = sorted([z for z in qualified if z["price"] > current_price], key=lambda z: z["price"])[:max_zones]

    nearest_support = {"price": supports[0]["price"], "touches": supports[0]["touches"]} if supports else None
    nearest_resistance = (
        {"price": resistances[0]["price"], "touches": resistances[0]["touches"]} if resistances else None
    )

    fib = _fibonacci_levels(pivot_highs, pivot_lows, len(history), fib_lookback_bars)
    fib_levels = fib["levels"] if fib else None
    fib_direction = fib["direction"] if fib else None

    # candidati per rottura/vicinanza: zone pivot + livelli fibonacci
    candidates = []
    for z in qualified:
        candidates.append({"price": z["price"], "type": "pivot", "touches": z["touches"]})
    if fib_levels:
        for ratio, price in fib_levels.items():
            candidates.append({"price": price, "type": "fibonacci", "touches": None, "ratio": ratio})

    result = _empty_result()
    result["nearest_support"] = nearest_support
    result["nearest_resistance"] = nearest_resistance
    result["fib_levels"] = fib_levels
    result["fib_direction"] = fib_direction

    if len(history) < 2:
        return result

    previous_close = float(history["Close"].iloc[-2])

    def label_for(cand):
        base = f"pivot ({cand['touches']} tocchi)" if cand["type"] == "pivot" else f"ritracciamento Fib {cand['ratio']}"
        if cand["type"] == "pivot" and fib_levels:
            for ratio, price in fib_levels.items():
                if abs(price - cand["price"]) / cand["price"] * 100 <= tolerance_pct:
                    return True, f"{base} + confluenza Fib {ratio}"
        return False, base

    # 1. breakout/breakdown: previous_close da un lato della banda, current_price dall'altro
    breakout_candidates = []
    for cand in candidates:
        price = cand["price"]
        band_low = price * (1 - tolerance_pct / 100)
        band_high = price * (1 + tolerance_pct / 100)
        crossed_up = previous_close < band_low and current_price > band_high
        crossed_down = previous_close > band_high and current_price < band_low
        if crossed_up or crossed_down:
            breakout_candidates.append((cand, "breakout_resistance" if crossed_up else "breakdown_support"))

    if breakout_candidates:
        breakout_candidates.sort(key=lambda c: (-(c[0]["touches"] or 0), abs(c[0]["price"] - current_price)))
        cand, signal = breakout_candidates[0]
        confluence, label = label_for(cand)
        distance_pct = (current_price - cand["price"]) / cand["price"] * 100
        result.update(
            {
                "signal": signal,
                "value": round(distance_pct, 3),
                "level_price": cand["price"],
                "level_type": cand["type"],
                "level_label": label,
                "touches": cand["touches"],
                "confluence": confluence,
            }
        )
        return result

    # 2. near: distanza entro soglia attiva (isteresi)
    def active_threshold(signal_name):
        return proximity_pct * hysteresis_factor if previous_signal == signal_name else proximity_pct

    best_below, best_above = None, None
    for cand in candidates:
        distance_pct = (current_price - cand["price"]) / cand["price"] * 100
        if distance_pct >= 0:
            if best_below is None or distance_pct < best_below[1]:
                best_below = (cand, distance_pct)
        else:
            if best_above is None or abs(distance_pct) < abs(best_above[1]):
                best_above = (cand, distance_pct)

    near_support = best_below is not None and best_below[1] <= active_threshold("near_support")
    near_resistance = best_above is not None and abs(best_above[1]) <= active_threshold("near_resistance")

    if near_support and near_resistance:
        if abs(best_above[1]) < best_below[1]:
            near_support = False
        else:
            near_resistance = False

    if near_support:
        cand, distance_pct = best_below
        confluence, label = label_for(cand)
        result.update(
            {
                "signal": "near_support",
                "value": round(distance_pct, 3),
                "level_price": cand["price"],
                "level_type": cand["type"],
                "level_label": label,
                "touches": cand["touches"],
                "confluence": confluence,
            }
        )
    elif near_resistance:
        cand, distance_pct = best_above
        confluence, label = label_for(cand)
        result.update(
            {
                "signal": "near_resistance",
                "value": round(distance_pct, 3),
                "level_price": cand["price"],
                "level_type": cand["type"],
                "level_label": label,
                "touches": cand["touches"],
                "confluence": confluence,
            }
        )

    return result
