"""
Run giornaliero, dopo la chiusura dei mercati (GitHub Actions, lun-ven 21:30 UTC).

1. Legge i comandi Telegram del titolare ("pac fatto", "pac saltato", "stato").
2. Compravendite rapide:
   - aggiorna le operazioni "su carta" gia' aperte (docs/swing_log.json) e
     avvisa quando si chiudono;
   - cerca i setup di oggi sull'universo (universe.json), tiene solo quelli
     che sullo storico del titolo hanno guadagnato (docs/backtest.json), li
     ordina e ne propone al massimo quanti ne permettono i posti liberi
     (max_open) e il limite mensile (max_new_per_month).
3. PAC: il primo run di ogni mese calcola quanto investire e su cosa.
4. Scrive docs/state.json per la dashboard (senza importi personali).
"""

from datetime import date, datetime, timedelta, timezone

from common import (
    BACKTEST_PATH, ENCRYPTION_KEY, PRIVATE_STATE_PATH, STATE_PATH, SWING_LOG_PATH, TELEGRAM_CHAT_IDS,
    TELEGRAM_TOKEN, UNIVERSE_PATH, download_history, env_number, fx_to_eur, get_telegram_updates,
    load_config, load_encrypted_json, load_json, save_encrypted_json, save_json, send_telegram,
)
from pac import allocate, market_state, monthly_amount
from swing_strategy import currency_for, position_size, prepare, setup_signals, simulate_trade, summarize, trade_plan

SETUP_LABEL = {"pullback": "ritracciamento nel trend", "breakout": "rottura dei massimi a 20 giorni"}
MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
          "settembre", "ottobre", "novembre", "dicembre"]
CURRENCY_SYMBOL = {"EUR": "€", "USD": "$"}


def fmt_num(x: float, decimals: int = 2) -> str:
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_money(x: float, currency: str = "EUR", decimals: int = 2) -> str:
    return f"{fmt_num(x, decimals)} {CURRENCY_SYMBOL.get(currency, currency)}"


def fmt_pct(x: float, decimals: int = 1) -> str:
    return ("+" if x > 0 else "") + fmt_num(x, decimals) + "%"


# ---------------------------------------------------------------- comandi

def process_commands(private: dict, prices: dict, pac_cfg: dict) -> list:
    """Ritorna i messaggi di risposta da mandare al titolare."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_IDS:
        return []
    owner = TELEGRAM_CHAT_IDS[0]
    replies = []
    updates = get_telegram_updates(private.get("last_update_id", 0))
    for upd in updates:
        private["last_update_id"] = max(private.get("last_update_id", 0), upd["update_id"] + 1)
        msg = upd.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != owner or "text" not in msg:
            continue
        text = " ".join(msg["text"].lower().split())
        if text in ("pac fatto", "pac fatto!", "fatto pac"):
            replies.append(confirm_pac(private, done=True))
        elif text in ("pac saltato", "salta pac", "pac salta"):
            replies.append(confirm_pac(private, done=False))
        elif text in ("stato", "riepilogo", "/stato"):
            replies.append(pac_summary(private, prices, pac_cfg))
        elif text in ("aiuto", "help", "/help", "/start"):
            replies.append("Comandi: «pac fatto», «pac saltato», «stato».")
    return replies


def pending_pac(private: dict):
    hist = private.get("pac", {}).get("history", [])
    return hist[-1] if hist and hist[-1]["status"] == "pending" else None


def confirm_pac(private: dict, done: bool) -> str:
    rec = pending_pac(private)
    if rec is None:
        return "Non c'e' nessun acquisto PAC in attesa di conferma."
    pac = private["pac"]
    if not done:
        rec["status"] = "skipped"
        return f"Ok, PAC di {rec['label']} segnato come saltato."
    for b in rec["buys"]:
        pac["units"][b["key"]] = pac["units"].get(b["key"], 0.0) + b["amount"] / b["price"]
        pac["invested"][b["key"]] = pac["invested"].get(b["key"], 0.0) + b["amount"]
    rec["status"] = "done"
    total = sum(pac["invested"].values())
    return f"✅ PAC di {rec['label']} registrato: {fmt_money(sum(b['amount'] for b in rec['buys']), decimals=0)}. Investito totale: {fmt_money(total, decimals=0)}."


def pac_summary(private: dict, prices: dict, pac_cfg: dict) -> str:
    pac = private.get("pac", {})
    budget = env_number("PAC_BUDGET", pac_cfg.get("budget_default", 40000))
    lines = ["<b>PAC – situazione</b>"]
    tot_inv, tot_val = 0.0, 0.0
    for a in pac_cfg["assets"]:
        inv = pac.get("invested", {}).get(a["key"], 0.0)
        units = pac.get("units", {}).get(a["key"], 0.0)
        if inv <= 0:
            continue
        val = units * prices.get(a["key"], 0.0) if a["key"] in prices else inv
        tot_inv += inv
        tot_val += val
        lines.append(f"• {a['name']}: {fmt_money(val, decimals=0)} (investiti {fmt_money(inv, decimals=0)}, {fmt_pct((val / inv - 1) * 100)})")
    if tot_inv == 0:
        lines.append("Nessun acquisto PAC registrato finora.")
    else:
        lines.append(f"Totale: {fmt_money(tot_val, decimals=0)} su {fmt_money(tot_inv, decimals=0)} investiti ({fmt_pct((tot_val / tot_inv - 1) * 100)})")
        for a in pac_cfg["assets"]:
            units = pac.get("units", {}).get(a["key"], 0.0)
            if a["key"] in prices and tot_val > 0:
                w = units * prices[a["key"]] / tot_val * 100
                lines.append(f"   {a['name']}: {fmt_num(w, 0)}% (obiettivo {a['weight']}%)")
    lines.append(f"Budget restante: {fmt_money(max(budget - tot_inv, 0), decimals=0)} su {fmt_money(budget, decimals=0)}")
    return "\n".join(lines)


# ---------------------------------------------------------------- PAC

def run_pac(private: dict, pac_cfg: dict, data: dict, today: date):
    """Ritorna (messaggio|None, info_mercato_pubblica)."""
    ref = pac_cfg["reference_ticker"]
    if ref not in data:
        return None, None
    state = market_state(data[ref]["Close"], pac_cfg)
    public = {"reference": ref, **state}

    pac = private.setdefault("pac", {"units": {}, "invested": {}, "history": []})
    month_key = today.strftime("%Y-%m")
    if any(h["month"] == month_key for h in pac["history"]):
        return None, public

    notes = []
    old = pending_pac(private)
    if old is not None:
        old["status"] = "expired"
        notes.append(f"⚠️ Il PAC di {old['label']} non e' stato confermato: non l'ho conteggiato.")

    prices = {a["key"]: float(data[a["ticker"]]["Close"].iloc[-1]) for a in pac_cfg["assets"] if a["ticker"] in data}
    missing = [a["name"] for a in pac_cfg["assets"] if a["key"] not in prices]
    if missing:
        print("PAC: prezzi mancanti per", missing, "- rimando a domani")
        return None, public

    budget = env_number("PAC_BUDGET", pac_cfg.get("budget_default", 40000))
    base = env_number("PAC_MONTHLY_BASE", pac_cfg.get("monthly_base_default", 3000))
    invested = sum(pac["invested"].values())
    min_order = pac_cfg.get("min_order_eur", 200)
    amount = monthly_amount(base, state["multiplier"], budget, invested, min_order)
    label = f"{MONTHS[today.month - 1]} {today.year}"

    if amount <= 0:
        pac["history"].append({"month": month_key, "label": label, "status": "complete", "buys": []})
        return f"📅 <b>PAC {label}</b>: budget di {fmt_money(budget, decimals=0)} gia' tutto investito. Niente da comprare.", public

    buys = allocate(amount, pac_cfg["assets"], prices, pac["units"], pac_cfg.get("max_buys_per_month", 2), min_order)
    by_key = {a["key"]: a for a in pac_cfg["assets"]}
    for b in buys:
        b["price"] = prices[b["key"]]
    pac["history"].append({"month": month_key, "label": label, "status": "pending",
                           "multiplier": state["multiplier"], "buys": buys})

    why = f"{fmt_pct(state['drawdown_pct'])} dai massimi a 1 anno"
    if state["above_sma_pct"] is not None:
        why += f", {fmt_pct(state['above_sma_pct'])} rispetto alla media 200gg"
    lines = notes + [
        f"📅 <b>PAC {label}</b>",
        f"Mercato (MSCI World): {why} → <b>×{fmt_num(state['multiplier'], 2)}</b>",
        f"Questo mese investi <b>{fmt_money(amount, decimals=0)}</b>:",
    ]
    for b in buys:
        a = by_key[b["key"]]
        lines.append(f"• {fmt_money(b['amount'], decimals=0)} su {a['name']} (ISIN {a['isin']})")
    lines += [
        f"Investito finora: {fmt_money(invested, decimals=0)} su {fmt_money(budget, decimals=0)} ({fmt_num(invested / budget * 100 if budget else 0, 0)}%)",
        "Quando hai comprato rispondi «pac fatto» (oppure «pac saltato»).",
    ]
    return "\n".join(lines), public


# ---------------------------------------------------------------- swing

def update_paper_trades(log: dict, inds: dict, cfg: dict) -> list:
    """Ri-simula le operazioni aperte con i dati nuovi. Ritorna quelle chiuse oggi."""
    from backtest import cost_for

    just_closed = []
    for tr in log["trades"]:
        if tr["status"] not in ("pending", "open"):
            continue
        ind = inds.get(tr["ticker"])
        if ind is None:
            continue
        dates = [d.date().isoformat() for d in ind.index]
        if tr["signal_date"] not in dates:
            continue
        res = simulate_trade(ind, dates.index(tr["signal_date"]), tr, cost_for(tr["ticker"], cfg))
        res.pop("exit_idx", None)
        tr.update(res)
        if res["status"] in ("closed", "skipped"):
            just_closed.append(tr)
    return just_closed


def evaluate(ticker: str, setup: str, backtest: dict, cfg: dict):
    """(proponibile, statistiche titolo, punteggio)."""
    sw = backtest.get("swing", {})
    agg = sw.get("setups", {}).get(setup, {})
    tk = sw.get("tickers", {}).get(ticker, {}).get("setups", {}).get(setup, {})
    min_n = cfg.get("min_trades_ticker", 8)
    enough = tk.get("trades", 0) >= min_n
    score = tk.get("expectancy_r", 0.0) if enough else -1.0
    if not cfg.get("require_positive_backtest", True):
        return True, tk, score
    ok = agg.get("expectancy_r", 0) > 0 and enough and tk.get("expectancy_r", 0) > 0
    return ok, tk, score


def find_setups(inds: dict, universe: list, backtest: dict, cfg: dict, today: date) -> list:
    names = {s["ticker"]: s["name"] for s in universe}
    found = []
    for t, ind in inds.items():
        if t not in names or len(ind) < cfg.get("trend_sma", 200) + 5:
            continue
        last_date = ind.index[-1].date()
        if (today - last_date).days > 4:
            continue  # dati vecchi (titolo sospeso/delistato)
        for setup, sig in setup_signals(ind, cfg).items():
            if not bool(sig.iloc[-1]):
                continue
            ok, stats, score = evaluate(t, setup, backtest, cfg)
            plan = trade_plan(ind, len(ind) - 1, setup, cfg)
            found.append({"ticker": t, "name": names[t], "eligible": ok, "score": score, "stats": stats, **plan})
    found.sort(key=lambda f: -f["score"])
    return found


def setup_message(s: dict, size: dict, currency: str) -> str:
    stop_pct = (s["stop"] / s["entry_ref"] - 1) * 100
    lines = [
        f"🟢 <b>{s['name']}</b> ({s['ticker']}) – {SETUP_LABEL[s['setup']]}",
        f"Compra all'apertura di domani (~{fmt_money(s['entry_ref'], currency)})",
        f"Stop: <b>{fmt_money(s['stop'], currency)}</b> ({fmt_pct(stop_pct)}) – inseriscilo subito come ordine stop",
    ]
    if s["exit_on_sma"]:
        tgt = f" (oggi ~{fmt_money(s['indicative_target'], currency)})" if s.get("indicative_target") else ""
        lines.append(f"Uscita: alla prima chiusura sopra la media a 5 giorni{tgt}, o dopo {s['max_days']} sedute")
    else:
        tgt_pct = (s["target"] / s["entry_ref"] - 1) * 100
        lines.append(f"Obiettivo: <b>{fmt_money(s['target'], currency)}</b> ({fmt_pct(tgt_pct)}), o uscita dopo {s['max_days']} sedute")
    if size.get("qty", 0) > 0:
        lines.append(f"Quantità: {size['qty']} → {fmt_money(size['value_eur'], decimals=0)}, rischio max {fmt_money(size['risk_eur'], decimals=0)}")
    else:
        lines.append("Quantità: prezzo troppo alto per il rischio impostato (servono azioni frazionate)")
    st = s.get("stats") or {}
    if st.get("trades"):
        lines.append(
            f"Storico su questo titolo: {st['trades']} operazioni, {fmt_num(st['win_rate'], 0)}% vincenti, "
            f"media {fmt_pct(st['expectancy_pct'], 2)} a operazione, durata media {fmt_num(st['avg_days'], 0)} gg"
        )
    return "\n".join(lines)


def run_swing(log: dict, cfg: dict, universe: list, backtest: dict, inds: dict, today: date):
    """Ritorna (messaggi, setup_di_oggi_pubblici)."""
    messages = []
    for tr in update_paper_trades(log, inds, cfg):
        if tr["status"] == "skipped":
            messages.append(f"⚪️ {tr['name']} ({tr['ticker']}): apertura sotto lo stop, operazione annullata.")
        else:
            icon = "📗" if tr["return_pct"] > 0 else "📕"
            messages.append(
                f"{icon} Chiusa {tr['name']} ({tr['ticker']}): <b>{fmt_pct(tr['return_pct'], 2)}</b> "
                f"– {tr['exit_reason']}, {tr['days']} sedute"
            )

    found = find_setups(inds, universe, backtest, cfg, today)
    public_setups = found

    data_date = max((ind.index[-1].date().isoformat() for ind in inds.values()), default=None)
    if data_date is None or log.get("last_signal_date") == data_date:
        return messages, public_setups  # gia' scansionato oggi
    log["last_signal_date"] = data_date

    open_trades = [t for t in log["trades"] if t["status"] in ("pending", "open")]
    month = today.strftime("%Y-%m")
    used_this_month = sum(1 for t in log["trades"] if t["signal_date"][:7] == month and t["status"] != "skipped")
    slots = min(cfg.get("max_open", 3) - len(open_trades), cfg.get("max_new_per_month", 3) - used_this_month)
    held = {t["ticker"] for t in open_trades}

    eligible = [f for f in found if f["eligible"] and f["ticker"] not in held and f["signal_date"] == data_date]
    picks = []
    for f in eligible:
        if len(picks) >= max(slots, 0):
            break
        if f["ticker"] not in {p["ticker"] for p in picks}:
            picks.append(f)

    capital = env_number("SWING_CAPITAL", cfg.get("capital_default", 10000))
    fx_cache = {}
    for p in picks:
        cur = currency_for(p["ticker"])
        if cur not in fx_cache:
            fx_cache[cur] = fx_to_eur(cur)
        size = position_size(p, capital, cfg.get("risk_pct", 1.0), cfg.get("max_open", 3), fx_cache[cur])
        messages.append(setup_message(p, size, cur))
        log["trades"].append({
            "id": f"{p['ticker']}-{p['signal_date']}-{p['setup']}", "ticker": p["ticker"], "name": p["name"],
            "status": "pending", **{k: p[k] for k in ("setup", "signal_date", "entry_ref", "stop", "target",
                                                      "exit_on_sma", "max_days", "atr", "indicative_target")},
        })

    others = len(eligible) - len(picks)
    if picks and others > 0:
        messages.append(f"(Altri {others} setup validi oggi, non proposti per rispettare i limiti di posizioni/operazioni.)")
    elif not picks and eligible and slots <= 0:
        messages.append(f"{len(eligible)} setup validi oggi, ma hai già {len(open_trades)} posizioni aperte o hai raggiunto il limite del mese.")
    return messages, public_setups


# ---------------------------------------------------------------- main

def main():
    today = datetime.now(timezone.utc).date()
    config = load_config()
    universe = load_json(UNIVERSE_PATH, {"stocks": []})["stocks"]
    backtest = load_json(BACKTEST_PATH, {})
    log = load_json(SWING_LOG_PATH, {"last_signal_date": None, "trades": []})
    private = load_encrypted_json(PRIVATE_STATE_PATH, {"last_update_id": 0, "pac": {"units": {}, "invested": {}, "history": []}})
    swing_cfg, pac_cfg = config.get("swing", {}), config.get("pac", {})

    tickers = {s["ticker"] for s in universe}
    tickers |= {t["ticker"] for t in log["trades"] if t["status"] in ("pending", "open")}
    if pac_cfg.get("enabled", True):
        tickers |= {a["ticker"] for a in pac_cfg["assets"]} | {pac_cfg["reference_ticker"]}
    data = download_history(sorted(tickers), swing_cfg.get("live_history_period", "2y"))
    inds = {t: prepare(df, swing_cfg) for t, df in data.items()}

    pac_prices = {a["key"]: float(data[a["ticker"]]["Close"].iloc[-1]) for a in pac_cfg.get("assets", []) if a["ticker"] in data}
    owner_msgs = process_commands(private, pac_prices, pac_cfg)

    public = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    pac_can_persist = bool(ENCRYPTION_KEY) or not TELEGRAM_TOKEN
    if pac_cfg.get("enabled", True):
        if pac_can_persist:
            msg, public["pac_market"] = run_pac(private, pac_cfg, data, today)
            if msg:
                owner_msgs.append(msg)
        else:
            print("PORTFOLIO_ENCRYPTION_KEY mancante: salto il PAC (non potrei salvarne lo stato).")

    if swing_cfg.get("enabled", True):
        if not backtest.get("swing") and swing_cfg.get("require_positive_backtest", True):
            print("Backtest assente: lancia il workflow 'Backtest' prima di ricevere proposte.")
        swing_msgs, public["setups_today"] = run_swing(log, swing_cfg, universe, backtest, inds, today)
        owner_msgs += swing_msgs

    # tutti i messaggi contengono importi/quantita' personali -> solo al titolare
    for m in owner_msgs:
        send_telegram(m, owner_only=True)

    if today.weekday() == 4:  # venerdi': riepilogo settimanale delle simulazioni
        closed = [t for t in log["trades"] if t["status"] == "closed"]
        st = summarize(closed)
        if st["trades"]:
            send_telegram(
                f"📊 <b>Simulazione compravendite</b>: {st['trades']} operazioni chiuse, "
                f"{fmt_num(st['win_rate'], 0)}% vincenti, media {fmt_pct(st['expectancy_pct'], 2)} a operazione.",
                owner_only=True,
            )

    closed = [t for t in log["trades"] if t["status"] == "closed"]
    public["paper"] = {
        "open": [t for t in log["trades"] if t["status"] in ("pending", "open")],
        "recent_closed": closed[-15:][::-1],
        "stats": summarize(closed),
    }
    public["universe_size"] = len(universe)
    save_json(SWING_LOG_PATH, log)
    save_json(STATE_PATH, public)
    if pac_can_persist:
        save_encrypted_json(PRIVATE_STATE_PATH, private)


if __name__ == "__main__":
    main()
