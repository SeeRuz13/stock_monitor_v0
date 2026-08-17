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
from fpdf import FPDF, XPos, YPos

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
    """
    Formato verticale a "card", una per titolo, pensato per essere aperto e
    scorso su telefono (nessuna tabella larga da zoomare in orizzontale).
    """
    tickers = sorted(state.get("stocks", {}).keys(), key=lambda t: state["stocks"][t].get("name", t))

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_left_margin(12)
    pdf.set_right_margin(12)
    pdf.add_page()
    content_width = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_font("Helvetica", "B", 15)
    pdf.multi_cell(content_width, 8, f"Stock Monitor - Report {today_str}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(content_width, 5, "Chiusure giornaliere e badge attuali, un titolo per blocco.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    for t in tickers:
        s = state["stocks"][t]
        name = s.get("name") or t
        price = s.get("last_price")
        delta = s.get("delta_pct")
        days = sorted(log.get(t, {}).get("days", []), key=lambda d: d["date"])[-max_days:]

        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(content_width, 6.5, f"{name}  ({t})", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_font("Helvetica", "", 10)
        price_line = f"Prezzo: {price:.2f}" if price is not None else "Prezzo: -"
        if delta is not None:
            price_line += f"   Delta oggi: {delta:+.2f}%"
        pdf.multi_cell(content_width, 5.5, price_line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.multi_cell(content_width, 5.5, f"S / R: {sr_label(s)}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        badge = badge_label(s)
        pdf.multi_cell(content_width, 5.5, f"Badge: {badge}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        count = s.get("signal_agreement_count", 0)
        context = s.get("signal_agreement_context") or []
        agreement_line = f"Segnali concordanti: {count}"
        if context:
            agreement_line += f" - {', '.join(context)}"
        pdf.multi_cell(content_width, 5.5, agreement_line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(90, 90, 90)
        if days:
            history_txt = ", ".join(f"{d['date'][5:]}: {d['close']:.2f}" for d in days if d.get("close") is not None)
            pdf.multi_cell(content_width, 5, f"Storico: {history_txt}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        else:
            pdf.multi_cell(content_width, 5, "Storico: nessun dato ancora accumulato", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)

        pdf.ln(1.5)
        y = pdf.get_y()
        pdf.set_draw_color(210, 210, 210)
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.ln(4)

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
