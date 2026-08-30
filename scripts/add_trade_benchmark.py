#!/usr/bin/env python3
"""add_trade_benchmark.py

Il buco più importante lasciato aperto finora: il dataset di trade
completi (BUY1/BUY2/BUY3 -> EXIT1/EXIT2, generato da backtest_fetch.py)
non ha MAI avuto un benchmark — a differenza di event_study.py e
confluence_study.py, che confrontano sempre il rendimento dell'evento
con un baseline dello stesso strumento.

Qui il benchmark è più delicato che negli altri due script: i trade
hanno durate diverse (days_held varia da 1 a 50+ giorni), quindi non
basta un orizzonte fisso (5/10/20gg) — serve, per ogni trade, il
rendimento medio che lo STESSO strumento ha prodotto storicamente su
un periodo della STESSA durata (giorni di borsa), calcolato su tutti i
punti di partenza possibili della sua serie storica in cache.

Legge SOLO la cache locale (data/raw_prices/*.json) + il dataset trade
già esistente — NESSUNA chiamata a yfinance. Aggiunge a ogni trade:
  baseline_avg_return_pct, excess_return_pct

Riscrive data/trades_dataset.json con questi campi aggiunti — la
struttura esistente resta invariata, solo arricchita (stesso pattern
già usato da add_chandelier_exit.py).
"""

import json
import os
import math

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADES_PATH = os.path.join(BASE_DIR, "data", "trades_dataset.json")
RAW_DIR = os.path.join(BASE_DIR, "data", "raw_prices")


def window_crosses_discontinuity(entry_idx, exit_idx, bad_indices_set):
    return any(entry_idx < b <= exit_idx for b in bad_indices_set)


def baseline_for_duration(closes, bad_indices_set, duration):
    """Rendimento medio a +duration giorni di borsa, calcolato su TUTTI i
    punti di partenza possibili della serie — il benchmark "a parità di
    durata" per quel trade specifico."""
    n = len(closes)
    if duration <= 0 or duration >= n:
        return None
    vals = []
    for i in range(n - duration):
        entry_price = closes[i]
        if not entry_price:
            continue
        if window_crosses_discontinuity(i, i + duration, bad_indices_set):
            continue
        vals.append((closes[i + duration] / entry_price - 1) * 100)
    return round(sum(vals) / len(vals), 3) if vals else None


def sanitize_nan(obj):
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_nan(v) for v in obj]
    return obj


def load_ticker_cache(ticker):
    fname = ticker.replace(".", "_") + ".json"
    fpath = os.path.join(RAW_DIR, fname)
    if not os.path.exists(fpath):
        return None
    with open(fpath, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    if not os.path.exists(TRADES_PATH):
        print(f"[ERROR] {TRADES_PATH} non trovato — esegui prima backtest_fetch.py")
        return

    with open(TRADES_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    trades = dataset.get("trades", [])
    print(f"Trade nel dataset: {len(trades)}")

    cache_by_ticker = {}
    baseline_cache = {}  # (ticker, duration) -> valore, per non ricalcolare la stessa durata più volte

    with_benchmark = 0
    no_cache = 0

    for idx, trade in enumerate(trades):
        ticker = trade["ticker"]
        duration = trade.get("days_held")

        if ticker not in cache_by_ticker:
            cache_by_ticker[ticker] = load_ticker_cache(ticker)

        rec = cache_by_ticker[ticker]
        if not rec or duration is None:
            no_cache += 1
            trade["baseline_avg_return_pct"] = None
            trade["excess_return_pct"] = None
            continue

        key = (ticker, duration)
        if key not in baseline_cache:
            bad_set = set(rec.get("bad_indices", []))
            baseline_cache[key] = baseline_for_duration(rec["c"], bad_set, duration)

        baseline = baseline_cache[key]
        trade["baseline_avg_return_pct"] = baseline
        if baseline is not None and trade.get("return_pct") is not None:
            trade["excess_return_pct"] = round(trade["return_pct"] - baseline, 3)
            with_benchmark += 1
        else:
            trade["excess_return_pct"] = None

        if (idx + 1) % 10000 == 0:
            print(f"  {idx + 1}/{len(trades)} trade processati")

    dataset["benchmark_note"] = (
        "baseline_avg_return_pct: rendimento medio dello stesso strumento su un periodo "
        "della STESSA durata (days_held) del trade, calcolato su tutti i punti di "
        "partenza possibili nello storico. excess_return_pct = return_pct - baseline: "
        "solo questo indica un vero effetto del motore di segnale, non il semplice "
        "drift generale dello strumento/mercato nel periodo."
    )

    with open(TRADES_PATH, "w", encoding="utf-8") as f:
        json.dump(sanitize_nan(dataset), f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    print(f"\nCompletato: {with_benchmark} trade con benchmark calcolato")
    print(f"  Senza cache/dati mancanti: {no_cache}")


if __name__ == "__main__":
    main()
