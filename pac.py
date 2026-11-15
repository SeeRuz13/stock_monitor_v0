"""
Accumulo tipo PAC "modulato".

Ogni mese si investe un importo base, moltiplicato in base allo stato del
mercato di riferimento (MSCI World):
  - piu' e' sceso dai massimi a 52 settimane, piu' si compra (fino a 2x)
  - se e' molto sopra la media a 200 giorni ("caro") si compra meno (0.75x)
fino a esaurire il budget totale.

L'importo del mese va solo agli 1-2 ETF piu' sotto il loro peso obiettivo:
cosi' il portafoglio si ribilancia da solo comprando (mai vendendo) e si
usano poche operazioni al mese (vincolo delle 10 operazioni gratuite).

Importi e posizioni sono personali: vivono solo in private_state.json
(cifrato) e nei messaggi Telegram al titolare, mai in docs/ (pubblico).
"""

import pandas as pd

from indicators import drawdown_from_high, sma


def market_state(close: pd.Series, cfg: dict) -> dict:
    dd = float(drawdown_from_high(close, cfg.get("high_window", 252)).iloc[-1])
    trend = sma(close, cfg.get("sma_window", 200))
    above_sma = float((close.iloc[-1] / trend.iloc[-1] - 1) * 100) if pd.notna(trend.iloc[-1]) else None
    return {"drawdown_pct": round(dd, 2), "above_sma_pct": round(above_sma, 2) if above_sma is not None else None,
            "multiplier": multiplier_for(dd, above_sma, cfg)}


def multiplier_for(drawdown_pct: float, above_sma_pct, cfg: dict) -> float:
    mult = 1.0
    # bande ordinate per profondita' crescente: [[5, 1.25], [10, 1.5], [20, 2.0]]
    for depth, m in sorted(cfg.get("drawdown_bands", []), key=lambda b: b[0]):
        if drawdown_pct <= -depth:
            mult = m
    if mult == 1.0 and above_sma_pct is not None and above_sma_pct > cfg.get("expensive_above_sma_pct", 15):
        mult = cfg.get("expensive_multiplier", 0.75)
    return mult


def multiplier_series(close: pd.Series, cfg: dict) -> pd.Series:
    """Stesso calcolo di market_state ma per ogni seduta (per il backtest)."""
    dd = drawdown_from_high(close, cfg.get("high_window", 252))
    above = (close / sma(close, cfg.get("sma_window", 200)) - 1) * 100
    return pd.Series(
        [multiplier_for(d, a if pd.notna(a) else None, cfg) for d, a in zip(dd, above)],
        index=close.index,
    )


def allocate(amount: float, assets: list, prices: dict, units: dict, max_buys: int, min_order: float) -> list:
    """
    Divide `amount` tra gli ETF piu' sotto peso. Ritorna [{key, amount}].
    assets: [{key, weight}], prices/units: {key: valore}.
    """
    total_w = sum(a["weight"] for a in assets)
    values = {a["key"]: units.get(a["key"], 0.0) * prices[a["key"]] for a in assets}
    total_after = sum(values.values()) + amount
    gaps = {a["key"]: max(a["weight"] / total_w * total_after - values[a["key"]], 0.0) for a in assets}

    picked = sorted(assets, key=lambda a: -gaps[a["key"]])[:max_buys]
    gap_sum = sum(gaps[a["key"]] for a in picked)
    if gap_sum <= 0:
        shares = {a["key"]: a["weight"] for a in picked}
        gap_sum = sum(shares.values())
    else:
        shares = {a["key"]: gaps[a["key"]] for a in picked}

    buys = [{"key": k, "amount": amount * v / gap_sum} for k, v in shares.items() if v > 0]
    # niente ordini troppo piccoli: l'importo va all'acquisto principale
    buys.sort(key=lambda b: -b["amount"])
    kept = [b for b in buys if b["amount"] >= min_order] or buys[:1]
    leftover = amount - sum(b["amount"] for b in kept)
    kept[0]["amount"] += leftover

    # arrotonda a 10 euro, il resto sul primo
    for b in kept:
        b["amount"] = round(b["amount"] / 10) * 10
    kept[0]["amount"] += round(amount - sum(b["amount"] for b in kept), 2)
    return [b for b in kept if b["amount"] > 0]


def monthly_amount(base: float, multiplier: float, budget: float, invested: float, min_order: float) -> float:
    remaining = max(budget - invested, 0.0)
    amount = min(base * multiplier, remaining)
    # se resta un "avanzo" piccolo, lo si investe insieme a questo mese
    if 0 < remaining - amount < min_order:
        amount = remaining
    return round(amount, 2) if amount >= min(min_order, remaining) else 0.0


def backtest_pac(close: pd.Series, cfg: dict, budget: float, base: float, horizon_months: int) -> dict:
    """
    Per ogni mese di partenza possibile nello storico, confronta su
    `horizon_months` mesi tre modi di investire lo stesso budget nel solo
    ETF di riferimento:
      - tutto subito (lump sum)
      - PAC semplice (importo base fisso ogni mese)
      - PAC modulato (importo base x moltiplicatore)
    Il contante non ancora investito rende 0. Ritorna valori medi finali e
    in quante finestre il modulato batte il semplice.
    """
    close = close.dropna()
    mult = multiplier_series(close, cfg)
    monthly = close.groupby([close.index.year, close.index.month]).head(1)
    month_dates = list(monthly.index)
    results = []
    for start in range(len(month_dates) - horizon_months):
        window = month_dates[start : start + horizon_months + 1]
        end_price = float(close.loc[window[-1]])
        out = {}
        for mode in ("plain", "modulated"):
            invested, units = 0.0, 0.0
            for d in window[:-1]:
                m = 1.0 if mode == "plain" else float(mult.loc[d])
                amt = min(base * m, budget - invested)
                if amt <= 0:
                    break
                units += amt / float(close.loc[d])
                invested += amt
            out[mode] = units * end_price + (budget - invested)
        out["lump_sum"] = budget / float(close.loc[window[0]]) * end_price
        out["start"] = window[0].date().isoformat()
        results.append(out)

    if not results:
        return {"windows": 0}
    n = len(results)
    avg = lambda k: round(sum(r[k] for r in results) / n, 2)
    return {
        "windows": n,
        "horizon_months": horizon_months,
        "first_start": results[0]["start"],
        "last_start": results[-1]["start"],
        "budget": budget,
        "base": base,
        "avg_final": {"lump_sum": avg("lump_sum"), "plain": avg("plain"), "modulated": avg("modulated")},
        "worst_final": {k: round(min(r[k] for r in results), 2) for k in ("lump_sum", "plain", "modulated")},
        "modulated_beats_plain_pct": round(sum(r["modulated"] > r["plain"] for r in results) / n * 100, 1),
        "lump_sum_beats_plain_pct": round(sum(r["lump_sum"] > r["plain"] for r in results) / n * 100, 1),
    }
