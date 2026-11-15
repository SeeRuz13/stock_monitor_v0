"""
Funzioni condivise: JSON, Telegram, cifratura, download dati da Yahoo Finance.
"""

import json
import os

import pandas as pd
import requests
from cryptography.fernet import Fernet, InvalidToken

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
UNIVERSE_PATH = os.path.join(BASE_DIR, "universe.json")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
BACKTEST_PATH = os.path.join(DOCS_DIR, "backtest.json")
STATE_PATH = os.path.join(DOCS_DIR, "state.json")
SWING_LOG_PATH = os.path.join(DOCS_DIR, "swing_log.json")
PRIVATE_STATE_PATH = os.path.join(BASE_DIR, "private_state.json")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_IDS = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
ENCRYPTION_KEY = os.environ.get("PORTFOLIO_ENCRYPTION_KEY")


# --- JSON ---

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_config():
    return load_json(CONFIG_PATH, {})


def env_number(name: str, default: float) -> float:
    """Importi in euro (capitale, budget PAC) letti da variabili d'ambiente
    (GitHub -> Settings -> Secrets and variables -> Actions -> Variables), cosi'
    non finiscono nel repo pubblico. Se non impostati si usa il default."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        print(f"Valore non valido per {name}: {raw!r}, uso {default}")
        return default


# --- cifratura (stato privato: PAC, importi) ---

def load_encrypted_json(path: str, default, key: str = None):
    key = key or ENCRYPTION_KEY
    if not os.path.exists(path) or not key:
        return default
    with open(path, "rb") as f:
        blob = f.read()
    if not blob:
        return default
    try:
        return json.loads(Fernet(key.encode()).decrypt(blob))
    except (InvalidToken, ValueError) as exc:
        print(f"Errore decifratura {path}: {exc}")
        return default


def save_encrypted_json(path: str, data, key: str = None):
    key = key or ENCRYPTION_KEY
    if not key:
        print(f"PORTFOLIO_ENCRYPTION_KEY non configurato, non salvo {path}")
        return
    payload = json.dumps(data, ensure_ascii=False).encode()
    with open(path, "wb") as f:
        f.write(Fernet(key.encode()).encrypt(payload))


# --- Telegram ---

def _post(chat_id: str, message: str):
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=15,
    )
    if not resp.ok:
        print(f"Errore invio Telegram a {chat_id}:", resp.status_code, resp.text)


def send_telegram(message: str, owner_only: bool = False):
    """owner_only=True per messaggi con importi personali (PAC, quantita'):
    vanno solo al primo chat_id, mai agli eventuali amici."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_IDS:
        print("Telegram non configurato. Messaggio:\n" + message + "\n")
        return
    for chat_id in TELEGRAM_CHAT_IDS[:1] if owner_only else TELEGRAM_CHAT_IDS:
        _post(chat_id, message)


def get_telegram_updates(offset: int) -> list:
    if not TELEGRAM_TOKEN:
        return []
    resp = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
        params={"offset": offset, "timeout": 0},
        timeout=15,
    )
    if not resp.ok:
        print("Errore getUpdates:", resp.status_code, resp.text)
        return []
    return resp.json().get("result", [])


# --- dati di mercato ---

def download_history(tickers: list, period: str) -> dict:
    """Ritorna {ticker: DataFrame[Open, High, Low, Close, Volume]} con prezzi
    rettificati (dividendi/split). I ticker senza dati vengono omessi."""
    import yfinance as yf

    if not tickers:
        return {}
    raw = yf.download(
        tickers,
        period=period,
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        progress=False,
        threads=True,
    )
    out = {}
    for t in tickers:
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            continue
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Open", "High", "Low", "Close"])
        if len(df) > 0:
            out[t] = df
    missing = sorted(set(tickers) - set(out))
    if missing:
        print("Nessun dato per:", ", ".join(missing))
    return out


def fx_to_eur(currency: str) -> float:
    """Quante unita' di `currency` vale 1 EUR (es. USD -> ~1.08).
    1.0 per EUR o se il cambio non e' disponibile."""
    if not currency or currency.upper() == "EUR":
        return 1.0
    try:
        data = download_history([f"EUR{currency.upper()}=X"], "5d")
        df = next(iter(data.values()))
        return float(df["Close"].iloc[-1])
    except Exception as exc:
        print(f"Cambio EUR/{currency} non disponibile ({exc}), uso 1.0")
        return 1.0
