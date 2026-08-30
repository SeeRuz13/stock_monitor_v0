"""
Tracking del portafoglio via comandi Telegram in ingresso ("comprato"/"venduto").

Gira dentro il run ogni 15 minuti di monitor.py (nessun server always-on): ad
ogni run si legge getUpdates (non bloccante), si processano i nuovi comandi,
si salva subito lo stato. Un comando applicato viene quindi recepito entro
15 minuti, non istantaneamente.

Solo il titolare (TELEGRAM_CHAT_IDS[0]) puo' dare comandi - i messaggi da
altre chat vengono ignorati silenziosamente.

portfolio.json e' cifrato (Fernet, chiave in PORTFOLIO_ENCRYPTION_KEY) perche'
il repo e' pubblico: a differenza di prezzi/segnali tecnici (gia' pubblici in
docs/state.json), quali titoli l'utente possiede davvero e' un'informazione
piu' sensibile.
"""

import json
import os
import re

import requests
from cryptography.fernet import Fernet, InvalidToken

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


# --- cifratura ---

def load_encrypted_json(path: str, default, key: str):
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


def save_encrypted_json(path: str, data, key: str):
    if not key:
        print("PORTFOLIO_ENCRYPTION_KEY non configurato, non salvo portfolio.json")
        return
    payload = json.dumps(data, ensure_ascii=False).encode()
    with open(path, "wb") as f:
        f.write(Fernet(key.encode()).encrypt(payload))


# --- ricezione comandi ---

def get_telegram_updates(token: str, offset: int, timeout_s: int = 15) -> list:
    url = TELEGRAM_API.format(token=token, method="getUpdates")
    resp = requests.get(url, params={"offset": offset, "timeout": 0}, timeout=timeout_s)
    if not resp.ok:
        print("Errore getUpdates:", resp.status_code, resp.text)
        return []
    return resp.json().get("result", [])


def _tokenize(text: str) -> list:
    return re.findall(r"[\w&]+", text.lower(), flags=re.UNICODE)


def _stock_name_tokens(stock: dict) -> set:
    return set(_tokenize(stock["name"]))


def match_stock(remainder_tokens: list, stocks: list) -> dict:
    """
    {"status": "matched", "stock": s} | {"status": "ambiguous", "candidates": [...]}
    | {"status": "no_match"}
    """
    token_set = set(remainder_tokens)
    exact = []
    for s in stocks:
        isin = (s.get("isin") or "").lower()
        ticker = (s.get("ticker") or "").lower()
        ticker_base = ticker.split(".")[0] if ticker else ""
        name_tokens = _stock_name_tokens(s)

        if isin and isin in token_set:
            exact.append(s)
            continue
        if ticker and ticker in token_set:
            exact.append(s)
            continue
        if ticker_base and len(ticker_base) >= 3 and ticker_base in token_set:
            exact.append(s)
            continue
        if name_tokens and name_tokens.issubset(token_set):
            exact.append(s)
            continue

    if len(exact) == 1:
        return {"status": "matched", "stock": exact[0]}
    if len(exact) > 1:
        return {"status": "ambiguous", "candidates": exact}

    partial = []
    for s in stocks:
        name_tokens = _stock_name_tokens(s)
        if len(name_tokens) < 2:
            continue
        if len(name_tokens & token_set) >= 2:
            partial.append(s)

    if len(partial) == 1:
        return {"status": "matched", "stock": partial[0]}
    if len(partial) > 1:
        return {"status": "ambiguous", "candidates": partial}
    return {"status": "no_match"}


def parse_command(text: str, stocks: list, buy_keywords: list, sell_keywords: list):
    """None se il messaggio non contiene nessuna parola chiave (non e' un comando)."""
    tokens = _tokenize(text)
    if not tokens:
        return None

    buy_set, sell_set = set(buy_keywords), set(sell_keywords)
    action = None
    remainder = []
    for tok in tokens:
        if action is None and tok in buy_set:
            action = "buy"
            continue
        if action is None and tok in sell_set:
            action = "sell"
            continue
        remainder.append(tok)
    if action is None:
        return None

    return {"action": action, **match_stock(remainder, stocks)}


def process_updates(updates: list, stocks: list, held_tickers: set, owner_chat_id: str,
                     buy_keywords: list, sell_keywords: list):
    """Ritorna (nuovo_held_set, [(chat_id, testo_risposta), ...], nuovo_offset|None)."""
    held = set(held_tickers)
    replies = []
    max_update_id = None

    for update in updates:
        max_update_id = update["update_id"] if max_update_id is None else max(max_update_id, update["update_id"])
        message = update.get("message")
        if not message or "text" not in message:
            continue
        chat_id = str(message["chat"]["id"])
        if chat_id != owner_chat_id:
            continue

        parsed = parse_command(message["text"], stocks, buy_keywords, sell_keywords)
        if parsed is None:
            continue

        if parsed["status"] == "no_match":
            replies.append((chat_id, "Non ho trovato nessun titolo corrispondente in watchlist. Usa nome, ticker o ISIN."))
            continue
        if parsed["status"] == "ambiguous":
            names = ", ".join(f"{c['name']} ({c['ticker']})" for c in parsed["candidates"])
            replies.append((chat_id, f"Comando ambiguo, corrispondono piu' titoli: {names}. Riprova specificando ticker o ISIN."))
            continue

        stock = parsed["stock"]
        ticker = stock["ticker"]
        label = f"{stock['name']} ({ticker})"
        if parsed["action"] == "buy":
            if ticker in held:
                replies.append((chat_id, f"{label} e' gia' in portafoglio."))
            else:
                held.add(ticker)
                replies.append((chat_id, f"Aggiunto al portafoglio: {label}."))
        else:
            if ticker not in held:
                replies.append((chat_id, f"{label} non risultava in portafoglio."))
            else:
                held.discard(ticker)
                replies.append((chat_id, f"Rimosso dal portafoglio: {label}."))

    new_offset = (max_update_id + 1) if max_update_id is not None else None
    return held, replies, new_offset
