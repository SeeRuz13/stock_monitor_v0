import json
import os
from datetime import datetime, date

import requests
import yfinance as yf

from trend_algorithm import detect_trend

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.json")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "docs", "state.json")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram non configurato, salto invio. Messaggio:", message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
        timeout=15,
    )
    if not resp.ok:
        print("Errore invio Telegram:", resp.status_code, resp.text)


def fetch_quote(ticker_symbol: str):
    t = yf.Ticker(ticker_symbol)
    fi = t.fast_info

    def get_first(keys):
        for key in keys:
            try:
                value = fi[key]
            except (KeyError, TypeError):
                continue
            if value is not None:
                return value
        raise KeyError(f"nessuna delle chiavi {keys} trovata in fast_info")

    open_price = get_first(["open", "regularMarketOpen"])
    last_price = get_first(["last_price", "lastPrice", "regularMarketPrice"])
    return float(open_price), float(last_price)


def fetch_history(ticker_symbol: str, period: str, interval: str):
    t = yf.Ticker(ticker_symbol)
    return t.history(period=period, interval=interval)


def check_threshold(entry_state, delta_pct, threshold_pct, today_str):
    """Ritorna (alert: bool) e aggiorna entry_state in place."""
    baseline_date = entry_state.get("baseline_date")
    if baseline_date != today_str:
        # nuovo giorno di borsa: reset baseline
        entry_state["baseline_date"] = today_str
        entry_state["baseline_delta_pct"] = 0.0

    baseline_delta = entry_state.get("baseline_delta_pct", 0.0)
    move_since_baseline = delta_pct - baseline_delta

    if abs(move_since_baseline) >= threshold_pct:
        entry_state["baseline_delta_pct"] = delta_pct
        return True
    return False


def main():
    watchlist = load_json(WATCHLIST_PATH, {"default_threshold_pct": 2.0, "stocks": []})
    config = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {"last_updated": None, "stocks": {}})

    # rimuove dallo stato i ticker non piu' presenti in watchlist (es. dopo una modifica)
    known_tickers = {s["ticker"] for s in watchlist.get("stocks", []) if s.get("ticker")}
    state["stocks"] = {k: v for k, v in state["stocks"].items() if k in known_tickers}

    market_cfg = config.get("market_data", {"history_period": "3mo", "history_interval": "1d"})
    trend_params = config.get("trend_algorithm", {})
    default_threshold = watchlist.get("default_threshold_pct", 2.0)
    today_str = date.today().isoformat()

    for stock in watchlist.get("stocks", []):
        if not stock.get("enabled", True) or not stock.get("ticker"):
            continue

        name = stock["name"]
        ticker_symbol = stock["ticker"]
        threshold_pct = stock.get("threshold_pct", default_threshold)

        entry_state = state["stocks"].setdefault(ticker_symbol, {})

        try:
            open_price, last_price = fetch_quote(ticker_symbol)
            delta_pct = (last_price - open_price) / open_price * 100
        except Exception as exc:
            print(f"[{name}] errore nel recupero quotazione: {exc}")
            continue

        entry_state.update(
            {
                "name": name,
                "last_price": round(last_price, 4),
                "open_price": round(open_price, 4),
                "delta_pct": round(delta_pct, 3),
                "last_checked": datetime.utcnow().isoformat() + "Z",
            }
        )

        # --- Check 1: soglia assoluta di variazione giornaliera ---
        if check_threshold(entry_state, delta_pct, threshold_pct, today_str):
            direction = "in salita" if delta_pct >= 0 else "in discesa"
            send_telegram(
                f"[SOGLIA] {name} ({ticker_symbol}) {direction}: {delta_pct:+.2f}% oggi "
                f"(apertura {open_price:.2f}, ora {last_price:.2f})"
            )
            entry_state["last_threshold_alert"] = datetime.utcnow().isoformat() + "Z"

        # --- Check 2: trend detection ---
        try:
            history = fetch_history(
                ticker_symbol,
                market_cfg.get("history_period", "3mo"),
                market_cfg.get("history_interval", "1d"),
            )
            trend = detect_trend(history, trend_params)
        except Exception as exc:
            print(f"[{name}] errore nel calcolo trend: {exc}")
            trend = {"signal": "none", "value": 0.0}

        previous_signal = entry_state.get("last_trend_signal", "none")
        entry_state["trend_value"] = trend["value"]
        entry_state["trend_adx"] = trend.get("adx", 0.0)

        if trend["signal"] != "none" and trend["signal"] != previous_signal:
            label = "rialzista" if trend["signal"] == "up" else "ribassista"
            send_telegram(
                f"[TREND] {name} ({ticker_symbol}): rilevato trend {label} "
                f"(MACD hist {trend['value']:+.3f}, ADX {trend.get('adx', 0):.1f})"
            )
            entry_state["last_trend_alert"] = datetime.utcnow().isoformat() + "Z"

        entry_state["last_trend_signal"] = trend["signal"]

    state["last_updated"] = datetime.utcnow().isoformat() + "Z"
    save_json(STATE_PATH, state)


if __name__ == "__main__":
    main()
