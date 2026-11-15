"""
Test offline (dati sintetici, nessuna rete). Lancia con:  python tests/test_core.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import load_config  # noqa: E402
from pac import allocate, backtest_pac, monthly_amount, multiplier_for  # noqa: E402
from swing_strategy import position_size, prepare, setup_signals, simulate_trade, summarize, trade_plan  # noqa: E402
from backtest import backtest_ticker  # noqa: E402


def synthetic(n=2500, seed=0, drift=0.0004, vol=0.015, start=100.0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = start * np.exp(np.cumsum(rets))
    opens = close * np.exp(rng.normal(0, vol / 3, n))
    high = np.maximum(opens, close) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    low = np.minimum(opens, close) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    idx = pd.bdate_range("2016-01-01", periods=n)
    return pd.DataFrame({"Open": opens, "High": high, "Low": low, "Close": close,
                         "Volume": rng.integers(1e5, 1e6, n).astype(float)}, index=idx)


def bars(rows):
    idx = pd.bdate_range("2024-01-01", periods=len(rows))
    df = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx)
    df["Volume"] = 1.0
    df["exit_sma"] = 1e9  # mai sopra la media: non interferisce
    return df


def test_simulate_stop_target_time():
    plan = {"stop": 95.0, "target": 110.0, "exit_on_sma": False, "max_days": 3}
    # signal at 0, entry open 100 at bar 1, target hit at bar 2
    r = simulate_trade(bars([[100, 101, 99, 100], [100, 102, 98, 101], [101, 111, 100, 109]]), 0, plan, 0.0)
    assert r["status"] == "closed" and r["exit"] == 110.0 and r["exit_reason"] == "obiettivo", r
    assert abs(r["r_multiple"] - 2.0) < 1e-9
    # stop e obiettivo nella stessa seduta -> stop (prudente)
    r = simulate_trade(bars([[100, 101, 99, 100], [100, 112, 94, 101]]), 0, plan, 0.0)
    assert r["exit_reason"] == "stop" and r["r_multiple"] == -1.0, r
    # gap sotto lo stop
    r = simulate_trade(bars([[100, 101, 99, 100], [100, 101, 99, 100], [90, 92, 89, 91]]), 0, plan, 0.0)
    assert r["exit_reason"].startswith("stop (apertura") and r["exit"] == 90, r
    # tempo massimo
    r = simulate_trade(bars([[100, 101, 99, 100]] + [[100, 101, 99, 100.5]] * 4), 0, plan, 0.0)
    assert r["exit_reason"] == "tempo massimo" and r["days"] == 3, r
    # apertura gia' sotto lo stop -> non si entra
    r = simulate_trade(bars([[100, 101, 99, 100], [94, 95, 93, 94]]), 0, plan, 0.0)
    assert r["status"] == "skipped", r
    # nessuna seduta dopo il segnale
    assert simulate_trade(bars([[100, 101, 99, 100]]), 0, plan, 0.0)["status"] == "pending"
    # costi riducono il risultato
    r = simulate_trade(bars([[100, 101, 99, 100], [100, 102, 98, 101], [101, 111, 100, 109]]), 0, plan, 0.1)
    assert r["return_pct"] < 10.0


def test_backtest_runs_on_synthetic():
    cfg = load_config()["swing"]
    res = backtest_ticker(synthetic(), "TEST.MI", cfg)
    assert set(res) == {"pullback", "breakout"}
    for setup, trades in res.items():
        assert trades, setup
        st = summarize(trades)
        assert st["trades"] == len(trades) and 0 <= st["win_rate"] <= 100
        # operazioni non sovrapposte e in ordine
        dates = [t["date"] for t in trades]
        assert dates == sorted(dates) and len(set(dates)) == len(dates)
        # nessuna perdita oltre lo stop salvo gap (R >= -1 - margine costi/gap)
        assert min(t["r_multiple"] for t in trades) > -5


def test_trade_plan_and_size():
    cfg = load_config()["swing"]
    ind = prepare(synthetic(), cfg)
    sig = setup_signals(ind, cfg)["pullback"]
    i = int(np.flatnonzero(sig.to_numpy())[-1])
    plan = trade_plan(ind, i, "pullback", cfg)
    assert plan["stop"] < plan["entry_ref"] and plan["target"] is None and plan["exit_on_sma"]
    size = position_size(plan, 10000, 1.0, 3, 1.0)
    assert size["risk_eur"] <= 100.0 + 1e-6 and size["value_eur"] <= 10000 / 3 + 1e-6


def test_pac_logic():
    cfg = load_config()["pac"]
    assert multiplier_for(-2, 5, cfg) == 1.0
    assert multiplier_for(-7, 0, cfg) == 1.25
    assert multiplier_for(-12, -5, cfg) == 1.5
    assert multiplier_for(-25, -15, cfg) == 2.0
    assert multiplier_for(0, 20, cfg) == 0.75

    assert monthly_amount(3000, 2.0, 40000, 0, 200) == 6000
    assert monthly_amount(3000, 1.0, 40000, 38000, 200) == 2000
    assert monthly_amount(3000, 1.0, 40000, 36900, 200) == 3100  # avanzo piccolo incluso
    assert monthly_amount(3000, 1.0, 40000, 40000, 200) == 0

    assets = cfg["assets"]
    prices = {a["key"]: 100.0 for a in assets}
    # portafoglio vuoto: compra i 2 ETF con peso maggiore
    buys = allocate(3000, assets, prices, {}, 2, 200)
    assert sum(b["amount"] for b in buys) == 3000 and {b["key"] for b in buys} == {"world", "bond"}, buys
    # world gia' sovrappesato -> non lo compra
    buys = allocate(3000, assets, prices, {"world": 300, "bond": 10}, 2, 200)
    assert "world" not in {b["key"] for b in buys} and sum(b["amount"] for b in buys) == 3000, buys
    # importo piccolo: un solo ordine
    buys = allocate(250, assets, prices, {}, 2, 200)
    assert len(buys) == 1 and buys[0]["amount"] == 250, buys

    res = backtest_pac(synthetic()["Close"], cfg, 100.0, 7.5, 48)
    assert res["windows"] > 50 and set(res["avg_final"]) == {"lump_sum", "plain", "modulated"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
