"""
Scansione di mercato: prende i titoli piu' scambiati per volume (screener
pubblico di Yahoo Finance, stesso meccanismo non ufficiale ma senza
autenticazione gia' usato altrove nel progetto), fa girare gli stessi
identici algoritmi di trend/livelli gia' usati per la watchlist personale,
e seleziona i "top N" con l'andamento piu' chiaro.

Gira una volta al giorno dentro daily_report.py (non nel ciclo ogni 15 minuti
di monitor.py: 100 titoli x 2 storici + 1 quotazione = ~300 chiamate,
troppe per farlo ogni 15 min). Nessun alert Telegram per questi titoli -
solo una sezione nel PDF giornaliero, per tenere il rumore sotto controllo.

Classifica "andamento piu' chiaro": segnali indipendenti concordanti
(stessa metrica gia' calcolata per la watchlist, vedi signal_agreement in
monitor.py) come criterio principale, ADX come spareggio in caso di parita'
- riusa la logica esistente, nessun nuovo criterio da inventare.
"""

import requests

from trend_algorithm import detect_trend
from levels_algorithm import detect_levels
from monitor import fetch_quote, fetch_history, signal_agreement

SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"


def fetch_most_active_tickers(count: int = 100) -> list:
    """Ritorna una lista di {"symbol": ..., "name": ...}, ordinata per volume
    (l'ordine dello screener stesso), senza duplicati."""
    resp = requests.get(
        SCREENER_URL,
        params={"formatted": "false", "scrIds": "most_actives", "count": count, "start": 0},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    if not resp.ok:
        print("Errore fetch most_actives:", resp.status_code, resp.text)
        return []
    quotes = resp.json().get("finance", {}).get("result", [{}])[0].get("quotes", [])
    seen = set()
    tickers = []
    for q in quotes:
        symbol = q.get("symbol")
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        tickers.append({"symbol": symbol, "name": q.get("shortName") or symbol})
    return tickers


def scan_market(tickers: list, market_cfg: dict, trend_params: dict, levels_params: dict, top_n: int = 10) -> list:
    """
    Per ogni ticker: quotazione + storico, detect_trend + detect_levels,
    stesso identico calcolo della watchlist personale. Ritorna i primi
    `top_n` ordinati per (signal_agreement_count desc, adx desc), scartando
    chi non ha nessun segnale (count 0) - "andamento poco chiaro" non ha
    senso in classifica.
    """
    results = []
    for item in tickers:
        symbol = item["symbol"]
        try:
            open_price, last_price = fetch_quote(symbol)
            delta_pct = (last_price - open_price) / open_price * 100
        except Exception as exc:
            print(f"[scan {symbol}] errore quotazione: {exc}")
            continue

        try:
            history = fetch_history(symbol, market_cfg.get("history_period", "3mo"), market_cfg.get("history_interval", "1d"))
            trend = detect_trend(history, trend_params)
        except Exception as exc:
            print(f"[scan {symbol}] errore trend: {exc}")
            trend = {"signal": "none", "value": 0.0, "adx": 0.0}

        try:
            levels_history = fetch_history(symbol, market_cfg.get("levels_history_period", "6mo"), market_cfg.get("history_interval", "1d"))
            levels = detect_levels(levels_history, levels_params, last_price, "none")
        except Exception as exc:
            print(f"[scan {symbol}] errore livelli: {exc}")
            levels = {"signal": "none", "value": 0.0, "level_price": None, "level_label": "", "confluence": False, "volatility_confirmation": False}

        votes = signal_agreement(trend["signal"], levels)
        if not votes:
            continue

        results.append({
            "symbol": symbol,
            "name": item["name"],
            "last_price": last_price,
            "delta_pct": delta_pct,
            "trend_signal": trend["signal"],
            "adx": trend.get("adx", 0.0),
            "level_signal": levels["signal"],
            "level_label": levels.get("level_label", ""),
            "signal_agreement_count": len(votes),
            "signal_agreement_context": votes,
        })

    results.sort(key=lambda r: (-r["signal_agreement_count"], -r["adx"]))
    return results[:top_n]
