"""
Compravendite rapide (2-15 giorni), SOLO ACQUISTI (niente vendite allo scoperto).

Due setup, entrambi attivi solo se il titolo e' sopra la media a 200 giorni
(tendenza di fondo positiva):

  pullback  - il titolo e' in salita ma ha avuto qualche giorno di calo
              (RSI a 2 giorni molto basso). Si compra il rimbalzo, si esce quando
              il prezzo richiude sopra la media a 5 giorni.
  breakout  - il titolo chiude sopra il massimo delle ultime 20 sedute con
              volumi sopra la media. Si esce a obiettivo (multiplo di ATR).

Ogni operazione ha un piano deciso PRIMA di entrare: stop (multiplo di ATR sotto
l'entrata), obiettivo, durata massima. La stessa funzione simulate_trade() serve
sia per il backtest storico sia per seguire le operazioni "su carta" dal vivo,
cosi' i due risultati sono confrontabili.

Ingresso simulato all'APERTURA della seduta successiva al segnale (il segnale si
calcola sulla chiusura, quindi non si puo' entrare prima). Se stop e obiettivo
vengono toccati nella stessa seduta si assume lo stop (ipotesi prudente).
"""

import math

import pandas as pd

from indicators import atr, rsi, sma

SUFFIX_CURRENCY = {
    "MI": "EUR", "PA": "EUR", "DE": "EUR", "AS": "EUR", "MC": "EUR", "BR": "EUR",
    "HE": "EUR", "LS": "EUR", "VI": "EUR", "IR": "EUR",
    "SW": "CHF", "CO": "DKK", "ST": "SEK", "OL": "NOK",
}


def currency_for(ticker: str) -> str:
    if "." not in ticker:
        return "USD"
    return SUFFIX_CURRENCY.get(ticker.rsplit(".", 1)[1].upper(), "EUR")


def prepare(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    s = params.get("setups", {})
    pb = s.get("pullback", {})
    bo = s.get("breakout", {})
    ind = df.copy()
    ind["trend_sma"] = sma(ind["Close"], params.get("trend_sma", 200))
    ind["atr"] = atr(ind, params.get("atr_period", 14))
    ind["rsi_short"] = rsi(ind["Close"], pb.get("rsi_period", 2))
    ind["exit_sma"] = sma(ind["Close"], pb.get("exit_sma", 5))
    lookback = bo.get("lookback", 20)
    ind["prior_high"] = ind["High"].rolling(lookback, min_periods=lookback).max().shift(1)
    ind["prior_volume"] = ind["Volume"].rolling(lookback, min_periods=lookback).mean().shift(1)
    return ind


def setup_signals(ind: pd.DataFrame, params: dict) -> dict:
    """{nome_setup: Series booleana} - True nelle sedute in cui il setup scatta."""
    s = params.get("setups", {})
    uptrend = ind["Close"] > ind["trend_sma"]
    valid = ind["atr"].notna() & (ind["atr"] > 0)
    out = {}

    pb = s.get("pullback", {})
    if pb.get("enabled", True):
        out["pullback"] = uptrend & valid & (ind["rsi_short"] < pb.get("rsi_max", 10))

    bo = s.get("breakout", {})
    if bo.get("enabled", True):
        has_volume = ind["prior_volume"] > 0
        out["breakout"] = (
            uptrend
            & valid
            & (ind["Close"] > ind["prior_high"])
            & (~has_volume | (ind["Volume"] > ind["prior_volume"] * bo.get("volume_mult", 1.5)))
        )
    return out


def trade_plan(ind: pd.DataFrame, i: int, setup: str, params: dict) -> dict:
    cfg = params["setups"][setup]
    row = ind.iloc[i]
    ref = float(row["Close"])
    a = float(row["atr"])
    target_atr = cfg.get("target_atr")
    plan = {
        "setup": setup,
        "signal_date": ind.index[i].date().isoformat(),
        "entry_ref": round(ref, 4),
        "stop": round(ref - cfg.get("stop_atr", 2.0) * a, 4),
        "target": round(ref + target_atr * a, 4) if target_atr else None,
        "exit_on_sma": setup == "pullback",
        "max_days": cfg.get("max_days", 10),
        "atr": round(a, 4),
    }
    if plan["exit_on_sma"] and pd.notna(row["exit_sma"]):
        plan["indicative_target"] = round(float(row["exit_sma"]), 4)
    else:
        plan["indicative_target"] = plan["target"]
    return plan


def simulate_trade(ind: pd.DataFrame, signal_idx: int, plan: dict, cost_pct_per_side: float) -> dict:
    """
    Ritorna:
      {"status": "pending"}                       - non c'e' ancora la seduta di ingresso
      {"status": "skipped", ...}                  - apertura gia' sotto lo stop: non si entra
      {"status": "open", ...}                     - operazione ancora in corso (valutata a fine dati)
      {"status": "closed", "exit_idx": ..., ...}  - chiusa (stop/obiettivo/uscita/tempo)
    """
    entry_idx = signal_idx + 1
    if entry_idx >= len(ind):
        return {"status": "pending"}

    opens, highs, lows, closes = (ind[c].to_numpy() for c in ("Open", "High", "Low", "Close"))
    exit_sma = ind["exit_sma"].to_numpy()
    stop, target = plan["stop"], plan["target"]
    entry = float(opens[entry_idx])
    if entry <= stop:
        return {"status": "skipped", "reason": "apertura sotto lo stop", "entry_date": ind.index[entry_idx].date().isoformat()}

    risk = entry - stop
    exit_price, reason, exit_idx = None, None, None
    for j in range(entry_idx, len(ind)):
        o, h, lo, c = opens[j], highs[j], lows[j], closes[j]
        days = j - entry_idx + 1
        if j > entry_idx and o <= stop:
            exit_price, reason = o, "stop (apertura in gap)"
        elif lo <= stop:
            exit_price, reason = stop, "stop"
        elif target is not None and j > entry_idx and o >= target:
            exit_price, reason = o, "obiettivo (apertura in gap)"
        elif target is not None and h >= target:
            exit_price, reason = target, "obiettivo"
        elif plan.get("exit_on_sma") and c > exit_sma[j]:
            exit_price, reason = c, "chiusura sopra media 5gg"
        elif days >= plan["max_days"]:
            exit_price, reason = c, "tempo massimo"
        if exit_price is not None:
            exit_idx = j
            break

    cost = cost_pct_per_side / 100
    def result(px):
        net = (px * (1 - cost)) / (entry * (1 + cost)) - 1
        return {
            "entry_date": ind.index[entry_idx].date().isoformat(),
            "entry": round(entry, 4),
            "return_pct": round(net * 100, 3),
            # risultato in multipli del rischio iniziale: -1 = stop pieno, +2 = guadagno doppio del rischio
            "r_multiple": round(net * entry / risk, 3),
        }

    if exit_idx is None:
        out = result(float(closes[-1]))
        out.update({"status": "open", "last_price": round(float(closes[-1]), 4), "days": len(ind) - entry_idx})
        return out

    out = result(float(exit_price))
    out.update(
        {
            "status": "closed",
            "exit_idx": exit_idx,
            "exit_date": ind.index[exit_idx].date().isoformat(),
            "exit": round(float(exit_price), 4),
            "exit_reason": reason,
            "days": exit_idx - entry_idx + 1,
        }
    )
    return out


def summarize(trades: list) -> dict:
    """Statistiche su una lista di operazioni chiuse (dict con return_pct, r_multiple, days)."""
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    rets = [t["return_pct"] for t in trades]
    rs = [t["r_multiple"] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    return {
        "trades": n,
        "win_rate": round(len(wins) / n * 100, 1),
        "avg_win_pct": round(gross_win / len(wins), 2) if wins else 0.0,
        "avg_loss_pct": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "expectancy_pct": round(sum(rets) / n, 3),
        "expectancy_r": round(sum(rs) / n, 3),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "avg_days": round(sum(t["days"] for t in trades) / n, 1),
    }


def position_size(plan: dict, capital_eur: float, risk_pct: float, max_open: int, fx_per_eur: float) -> dict:
    """Quantita' tale che, se scatta lo stop, perdi al massimo risk_pct% del
    capitale; e comunque mai piu' di capital/max_open su una singola posizione."""
    risk_per_share = plan["entry_ref"] - plan["stop"]
    if risk_per_share <= 0:
        return {"qty": 0}
    max_risk_local = capital_eur * risk_pct / 100 * fx_per_eur
    max_value_local = capital_eur / max_open * fx_per_eur
    qty = min(math.floor(max_risk_local / risk_per_share), math.floor(max_value_local / plan["entry_ref"]))
    qty = max(qty, 0)
    return {
        "qty": qty,
        "value_eur": round(qty * plan["entry_ref"] / fx_per_eur, 2),
        "risk_eur": round(qty * risk_per_share / fx_per_eur, 2),
    }
