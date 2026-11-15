"""
Backtest: verifica sullo storico (default 10 anni) se i setup di trading e il
PAC modulato avrebbero funzionato. Gira una volta a settimana (GitHub Actions)
e scrive docs/backtest.json, che daily_run.py usa per decidere quali setup
proporre: un setup che sullo storico di un titolo ha perso soldi non viene
proposto su quel titolo.

Limiti da tenere a mente: il passato non garantisce il futuro; i titoli
dell'universo sono quelli grandi OGGI (chi e' fallito o uscito dagli indici non
c'e', e questo gonfia un po' i risultati); tasse (26%) non incluse.
"""

from datetime import datetime, timezone

from common import BACKTEST_PATH, UNIVERSE_PATH, download_history, env_number, load_config, load_json, save_json
from pac import backtest_pac
from swing_strategy import currency_for, prepare, setup_signals, simulate_trade, summarize, trade_plan


def cost_for(ticker: str, cfg: dict) -> float:
    cost = cfg.get("cost_pct_per_side", 0.1)
    if currency_for(ticker) != "EUR":
        cost += cfg.get("non_eur_extra_cost_pct_per_side", 0.0)
    return cost


def backtest_ticker(df, ticker: str, cfg: dict) -> dict:
    """{setup: [operazioni chiuse]} - operazioni non sovrapposte per setup."""
    ind = prepare(df, cfg)
    signals = setup_signals(ind, cfg)
    cost = cost_for(ticker, cfg)
    out = {}
    for setup, sig in signals.items():
        trades = []
        next_free = 0
        for i in [k for k, v in enumerate(sig.to_numpy()) if v]:
            if i < next_free:
                continue
            plan = trade_plan(ind, i, setup, cfg)
            res = simulate_trade(ind, i, plan, cost)
            if res["status"] == "closed":
                trades.append({"date": res["entry_date"], "return_pct": res["return_pct"],
                               "r_multiple": res["r_multiple"], "days": res["days"]})
                next_free = res["exit_idx"] + 1
            elif res["status"] == "skipped":
                continue
            else:
                break
        out[setup] = trades
    return out


def run_swing_backtest(cfg: dict, universe: list) -> dict:
    tickers = [s["ticker"] for s in universe]
    data = download_history(tickers, cfg.get("backtest_history_period", "10y"))
    per_ticker = {}
    all_trades = {}
    by_market = {}
    by_year = {}
    for s in universe:
        t = s["ticker"]
        if t not in data or len(data[t]) < 300:
            continue
        res = backtest_ticker(data[t], t, cfg)
        per_ticker[t] = {"name": s["name"], "market": s.get("market"),
                         "setups": {k: summarize(v) for k, v in res.items()}}
        for setup, trades in res.items():
            all_trades.setdefault(setup, []).extend(trades)
            by_market.setdefault(setup, {}).setdefault(s.get("market", "?"), []).extend(trades)
            for tr in trades:
                by_year.setdefault(setup, {}).setdefault(tr["date"][:4], []).append(tr)

    return {
        "setups": {k: summarize(v) for k, v in all_trades.items()},
        "setups_by_market": {k: {m: summarize(v) for m, v in mk.items()} for k, mk in by_market.items()},
        "setups_by_year": {k: {y: summarize(v) for y, v in sorted(yr.items())} for k, yr in by_year.items()},
        "tickers": per_ticker,
    }


def run_pac_backtest(cfg: dict) -> dict:
    ref = cfg["reference_ticker"]
    data = download_history([ref], "max")
    if ref not in data:
        return {"error": f"nessun dato per {ref}"}
    # importi normalizzati (budget 100, base proporzionale): il confronto e' in %
    budget = env_number("PAC_BUDGET", cfg.get("budget_default", 40000))
    base = env_number("PAC_MONTHLY_BASE", cfg.get("monthly_base_default", 3000))
    res = backtest_pac(data[ref]["Close"], cfg, 100.0, 100.0 * base / budget, cfg.get("backtest_horizon_months", 48))
    res["reference_ticker"] = ref
    res["note"] = "Valori finali per 100 investiti (budget normalizzato a 100)."
    return res


def main():
    config = load_config()
    universe = load_json(UNIVERSE_PATH, {"stocks": []})["stocks"]
    result = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    if config.get("swing", {}).get("enabled", True):
        result["swing"] = run_swing_backtest(config["swing"], universe)
    if config.get("pac", {}).get("enabled", True):
        result["pac"] = run_pac_backtest(config["pac"])
    save_json(BACKTEST_PATH, result)

    for setup, st in result.get("swing", {}).get("setups", {}).items():
        print(f"{setup}: {st}")
    print("PAC:", result.get("pac"))


if __name__ == "__main__":
    main()
