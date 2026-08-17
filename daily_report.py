"""
Report giornaliero: accumula uno snapshot di chiusura al giorno per ogni titolo
in docs/daily_log.json (persistente, cresce di un giorno alla volta - stessa
logica "git come database" di monitor.py), genera un PDF con la tabella
riassuntiva + una colonna per ciascuno degli ultimi N giorni, e lo manda come
allegato via Telegram.

Gira una volta al giorno (vedi .github/workflows/daily_report.yml), separato
dal check ogni 15 minuti in monitor.py. Si disattiva mettendo
config.json -> "daily_report" -> "enabled": false, oppure disabilitando il
workflow da GitHub.
"""

import json
import os
from datetime import date

import requests
from fpdf import FPDF

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.json")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "docs", "state.json")
LOG_PATH = os.path.join(BASE_DIR, "docs", "daily_log.json")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_IDS = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def send_telegram_document(file_path: str, caption: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_IDS:
        print("Telegram non configurato, salto invio report.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    for chat_id in TELEGRAM_CHAT_IDS:
        with open(file_path, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (os.path.basename(file_path), f, "application/pdf")},
                timeout=30,
            )
        if not resp.ok:
            print(f"Errore invio documento Telegram a {chat_id}:", resp.status_code, resp.text)


def snapshot_from_state(s: dict) -> dict:
    return {
        "close": s.get("last_price"),
        "trend_signal": s.get("last_trend_signal", "none"),
        "level_signal": s.get("last_level_signal", "none"),
        "signal_agreement_count": s.get("signal_agreement_count", 0),
        "signal_agreement_context": s.get("signal_agreement_context", []),
    }


def update_daily_log(state: dict, log: dict, today_str: str) -> dict:
    for ticker, s in state.get("stocks", {}).items():
        entry = log.setdefault(ticker, {"name": s.get("name", ticker), "days": []})
        entry["name"] = s.get("name", ticker)
        days = entry["days"]
        record = {"date": today_str, **snapshot_from_state(s)}
        if days and days[-1]["date"] == today_str:
            days[-1] = record  # rilancio manuale nello stesso giorno: sovrascrive, non duplica
        else:
            days.append(record)
    return log


def badge_label(s: dict) -> str:
    tags = []
    trend = s.get("last_trend_signal")
    if trend == "up":
        tags.append("trend rialzista")
    elif trend == "down":
        tags.append("trend ribassista")
    level = s.get("last_level_signal")
    level_labels = {
        "near_support": "vicino a supporto",
        "near_resistance": "vicino a resistenza",
        "breakout_resistance": "rottura resistenza",
        "breakdown_support": "rottura supporto",
    }
    if level in level_labels:
        tags.append(level_labels[level])
    return " + ".join(tags) if tags else "-"


def sr_label(s: dict) -> str:
    sup = s.get("nearest_support")
    res = s.get("nearest_resistance")
    sup_s = f"{sup['price']:.2f}" if sup else "-"
    res_s = f"{res['price']:.2f}" if res else "-"
    return f"{sup_s} / {res_s}"


def build_pdf(state: dict, log: dict, max_days: int, out_path: str, today_str: str):
    tickers = sorted(state.get("stocks", {}).keys(), key=lambda t: state["stocks"][t].get("name", t))
    all_dates = sorted({d["date"] for t in tickers for d in log.get(t, {}).get("days", [])})
    shown_dates = all_dates[-max_days:]

    pdf = FPDF(orientation="L", unit="mm", format="A3")
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, f"Stock Monitor - Report giornaliero {today_str}", ln=1)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 6, f"Chiusure storiche: ultimi {len(shown_dates)} giorni monitorati (dati completi in daily_log.json)", ln=1)
    pdf.ln(2)

    headers = ["Titolo", "Prezzo", "D oggi %", "S / R", "Badge", "Segnali"] + shown_dates
    col_widths = [46, 16, 14, 26, 55, 12] + [16] * len(shown_dates)

    pdf.set_font("Helvetica", "B", 7)
    pdf.set_fill_color(225, 225, 220)
    for h, w in zip(headers, col_widths):
        pdf.cell(w, 7, h, border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 7)
    for t in tickers:
        s = state["stocks"][t]
        name = (s.get("name") or t)[:30]
        price = s.get("last_price")
        delta = s.get("delta_pct")

        row = [
            name,
            f"{price:.2f}" if price is not None else "-",
            f"{delta:+.2f}" if delta is not None else "-",
            sr_label(s),
            badge_label(s)[:38],
            str(s.get("signal_agreement_count", 0)),
        ]
        days_by_date = {d["date"]: d for d in log.get(t, {}).get("days", [])}
        for dt in shown_dates:
            d = days_by_date.get(dt)
            close = d.get("close") if d else None
            row.append(f"{close:.2f}" if close is not None else "-")

        for val, w in zip(row, col_widths):
            pdf.cell(w, 6, str(val), border=1)
        pdf.ln()

    pdf.output(out_path)


def main():
    config = load_json(CONFIG_PATH, {})
    report_cfg = config.get("daily_report", {"enabled": True, "max_days_shown": 10})
    if not report_cfg.get("enabled", True):
        print("Report giornaliero disabilitato in config.json (daily_report.enabled=false), esco.")
        return

    watchlist = load_json(WATCHLIST_PATH, {"stocks": []})
    known_tickers = {s["ticker"] for s in watchlist.get("stocks", []) if s.get("ticker")}

    state = load_json(STATE_PATH, {"stocks": {}})
    log = load_json(LOG_PATH, {})
    log = {k: v for k, v in log.items() if k in known_tickers}

    today_str = date.today().isoformat()
    log = update_daily_log(state, log, today_str)
    save_json(LOG_PATH, log)

    pdf_path = os.path.join(BASE_DIR, f"report_{today_str}.pdf")
    build_pdf(state, log, report_cfg.get("max_days_shown", 10), pdf_path, today_str)

    send_telegram_document(pdf_path, f"Report giornaliero Stock Monitor - {today_str}")

    if os.path.exists(pdf_path):
        os.remove(pdf_path)


if __name__ == "__main__":
    main()
