import json
import os
from datetime import datetime, date

import requests
import yfinance as yf

from trend_algorithm import detect_trend
from levels_algorithm import detect_levels
from portfolio import (
    get_telegram_updates,
    process_updates,
    load_encrypted_json,
    save_encrypted_json,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.json")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "docs", "state.json")
PORTFOLIO_PATH = os.path.join(BASE_DIR, "portfolio.json")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_IDS = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
PORTFOLIO_KEY = os.environ.get("PORTFOLIO_ENCRYPTION_KEY")


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _post_telegram_message(chat_id: str, message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
        timeout=15,
    )
    if not resp.ok:
        print(f"Errore invio Telegram a {chat_id}:", resp.status_code, resp.text)


def send_telegram(message: str):
    """Broadcast a tutte le chat (titolare + eventuali amici in sola lettura)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_IDS:
        print("Telegram non configurato, salto invio. Messaggio:", message)
        return
    for chat_id in TELEGRAM_CHAT_IDS:
        _post_telegram_message(chat_id, message)


def send_telegram_to(chat_id: str, message: str):
    """Solo al destinatario indicato - usato per le conferme comprato/venduto,
    mai in broadcast agli amici."""
    if not TELEGRAM_TOKEN:
        print("Telegram non configurato, salto invio. Messaggio:", message)
        return
    _post_telegram_message(chat_id, message)


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


def signal_agreement(trend_signal: str, levels: dict) -> list:
    """
    Elenca i segnali indipendenti attualmente in linea sulla stessa direzione.
    Puramente descrittivo (fatti verificabili sullo stato attuale), non una
    previsione: 'near_support'/'near_resistance' non contano come conferma
    direzionale (il prezzo potrebbe rimbalzare o rompere), solo le rotture
    confermate (breakout/breakdown) e il trend contano come "voti" direzionali;
    la confluenza pivot+Fibonacci si aggiunge come ulteriore elemento a parte.
    """
    votes = []
    direction = None

    if trend_signal in ("up", "down"):
        direction = trend_signal
        votes.append("trend rialzista" if trend_signal == "up" else "trend ribassista")

    levels_signal = levels.get("signal")
    breakout_counted = False
    if levels_signal == "breakout_resistance" and direction in (None, "up"):
        votes.append("rottura resistenza")
        breakout_counted = True
    elif levels_signal == "breakdown_support" and direction in (None, "down"):
        votes.append("rottura supporto")
        breakout_counted = True

    if breakout_counted and levels.get("volatility_confirmation"):
        votes.append("espansione di volatilità (Bollinger)")

    if levels.get("confluence") and levels_signal != "none":
        votes.append("confluenza Fibonacci")

    return votes


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

    portfolio_cfg = config.get("portfolio", {
        "enabled": True,
        "held_threshold_pct": 1.0,
        "buy_keywords": ["comprato", "acquistato", "compro", "acquisto"],
        "sell_keywords": ["venduto", "vendo", "vendita"],
    })

    # --- Step 0: elabora comandi Telegram in ingresso (comprato/venduto) ---
    portfolio_state = load_encrypted_json(PORTFOLIO_PATH, {"held_tickers": [], "last_update_id": 0}, PORTFOLIO_KEY)
    if portfolio_cfg.get("enabled", True) and TELEGRAM_TOKEN and TELEGRAM_CHAT_IDS and PORTFOLIO_KEY:
        try:
            owner_chat_id = TELEGRAM_CHAT_IDS[0]
            updates = get_telegram_updates(TELEGRAM_TOKEN, portfolio_state.get("last_update_id", 0))
            held_set, replies, new_offset = process_updates(
                updates,
                watchlist.get("stocks", []),
                set(portfolio_state.get("held_tickers", [])),
                owner_chat_id,
                portfolio_cfg.get("buy_keywords", []),
                portfolio_cfg.get("sell_keywords", []),
            )
            portfolio_state["held_tickers"] = sorted(held_set)
            if new_offset is not None:
                portfolio_state["last_update_id"] = new_offset
            for chat_id, reply_text in replies:
                send_telegram_to(chat_id, reply_text)
        except Exception as exc:
            print(f"Errore nell'elaborazione dei comandi Telegram: {exc}")
        finally:
            save_encrypted_json(PORTFOLIO_PATH, portfolio_state, PORTFOLIO_KEY)

    held_tickers = set(portfolio_state.get("held_tickers", []))

    market_cfg = config.get("market_data", {"history_period": "3mo", "history_interval": "1d"})
    trend_params = config.get("trend_algorithm", {})
    levels_params = config.get("levels_algorithm", {})
    default_threshold = watchlist.get("default_threshold_pct", 2.0)
    today_str = date.today().isoformat()

    for stock in watchlist.get("stocks", []):
        if not stock.get("enabled", True) or not stock.get("ticker"):
            continue

        name = stock["name"]
        ticker_symbol = stock["ticker"]
        is_held = ticker_symbol in held_tickers
        held_tag = "\U0001F4CC " if is_held else ""
        if is_held:
            threshold_pct = stock.get("held_threshold_pct", portfolio_cfg.get("held_threshold_pct", default_threshold))
        else:
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
                f"[SOGLIA] {held_tag}{name} ({ticker_symbol}) {direction}: {delta_pct:+.2f}% oggi "
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
                f"[TREND] {held_tag}{name} ({ticker_symbol}): rilevato trend {label} "
                f"(MACD hist {trend['value']:+.3f}, ADX {trend.get('adx', 0):.1f})"
            )
            entry_state["last_trend_alert"] = datetime.utcnow().isoformat() + "Z"

        entry_state["last_trend_signal"] = trend["signal"]

        # --- Check 3: supporti/resistenze e Fibonacci ---
        try:
            levels_history = fetch_history(
                ticker_symbol,
                market_cfg.get("levels_history_period", "6mo"),
                market_cfg.get("history_interval", "1d"),
            )
            previous_level_signal = entry_state.get("last_level_signal", "none")
            levels = detect_levels(levels_history, levels_params, last_price, previous_level_signal)
        except Exception as exc:
            print(f"[{name}] errore nel calcolo livelli: {exc}")
            previous_level_signal = entry_state.get("last_level_signal", "none")
            levels = {
                "signal": "none", "value": 0.0, "level_price": None, "level_type": None,
                "level_label": "", "touches": None, "confluence": False,
                "nearest_support": None, "nearest_resistance": None,
                "fib_levels": None, "fib_direction": None,
                "volatility_confirmation": False,
                "bollinger_sma": None, "bollinger_upper": None, "bollinger_lower": None,
            }

        entry_state["nearest_support"] = levels["nearest_support"]
        entry_state["nearest_resistance"] = levels["nearest_resistance"]
        entry_state["fib_levels"] = levels["fib_levels"]
        entry_state["fib_direction"] = levels["fib_direction"]
        entry_state["level_signal_value"] = levels["value"]
        entry_state["bollinger_sma"] = levels.get("bollinger_sma")
        entry_state["bollinger_upper"] = levels.get("bollinger_upper")
        entry_state["bollinger_lower"] = levels.get("bollinger_lower")

        votes = signal_agreement(trend["signal"], levels)
        entry_state["signal_agreement_count"] = len(votes)
        entry_state["signal_agreement_context"] = votes

        if levels["signal"] != "none" and levels["signal"] != previous_level_signal:
            verb = {
                "near_support": "vicino al supporto",
                "near_resistance": "vicino alla resistenza",
                "breakout_resistance": "ha rotto la resistenza",
                "breakdown_support": "ha rotto il supporto",
            }[levels["signal"]]
            message = (
                f"[LIVELLO] {held_tag}{name} ({ticker_symbol}): prezzo {last_price:.2f} {verb} "
                f"{levels['level_price']:.2f} ({levels['value']:+.2f}%) — {levels['level_label']}"
            )
            if votes:
                message += f"\nContesto: {len(votes)} segnali indipendenti in linea — {', '.join(votes)}"
            send_telegram(message)
            entry_state["last_level_alert"] = datetime.utcnow().isoformat() + "Z"

        entry_state["last_level_signal"] = levels["signal"]

    state["last_updated"] = datetime.utcnow().isoformat() + "Z"
    save_json(STATE_PATH, state)


if __name__ == "__main__":
    main()
