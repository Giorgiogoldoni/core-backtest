#!/usr/bin/env python3
"""add_chandelier_exit.py

Per ogni trade già presente in data/trades_dataset.json (entrata
BUY1/BUY2/BUY3, uscita attuale via SAR flip EXIT1/EXIT2), simula in
PARALLELO dove sarebbe uscito con un Chandelier Exit (trailing stop
ATR-based: Stop = massimo più alto da quando sei entrato − 3×ATR14),
usando la cache prezzi già scaricata (data/raw_prices/*.json) — NESSUN
nuovo fetch yfinance.

Aggiunge ai trade esistenti i campi:
  chandelier_exit_date, chandelier_exit_price, chandelier_return_pct,
  chandelier_days_held, chandelier_still_open, chandelier_discarded_discontinuity

Riscrive data/trades_dataset.json con questi campi aggiunti — la
struttura esistente (usata da index.html) resta invariata, solo
arricchita.
"""

import json
import os
import math

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADES_PATH = os.path.join(BASE_DIR, "data", "trades_dataset.json")
RAW_DIR = os.path.join(BASE_DIR, "data", "raw_prices")

ATR_MULTIPLIER = 3
ATR_PERIOD = 14


def calc_atr(high, low, close, n=ATR_PERIOD):
    trs = []
    for i in range(len(close)):
        if i == 0:
            trs.append(high[i] - low[i])
        else:
            trs.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    atr_arr = [None] * len(close)
    if len(trs) < n + 1:
        return atr_arr
    atr = sum(trs[1:n + 1]) / n
    atr_arr[n] = atr
    for i in range(n + 1, len(trs)):
        atr = (atr * (n - 1) + trs[i]) / n
        atr_arr[i] = atr
    return atr_arr


def simulate_chandelier(highs, lows, closes, atr_arr, entry_idx, bad_indices_set):
    """Simula il trailing stop dal giorno dopo l'ingresso in avanti.
    Ritorna (exit_idx, discarded_discontinuity) — exit_idx None se ancora aperto a fine serie."""
    n = len(closes)
    highest_high = highs[entry_idx]
    for j in range(entry_idx + 1, n):
        if j in bad_indices_set:
            return None, True  # discontinuità di prezzo attraversata prima di un'uscita chiara
        highest_high = max(highest_high, highs[j])
        atr_j = atr_arr[j]
        if atr_j is None:
            continue
        stop_level = highest_high - ATR_MULTIPLIER * atr_j
        if closes[j] < stop_level:
            return j, False
    return None, False  # mai scattato entro la fine dello storico disponibile


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
    atr_by_ticker = {}
    date_index_by_ticker = {}

    added = 0
    still_open = 0
    discarded = 0
    no_cache = 0

    for trade in trades:
        ticker = trade["ticker"]

        if ticker not in cache_by_ticker:
            rec = load_ticker_cache(ticker)
            cache_by_ticker[ticker] = rec
            if rec:
                atr_by_ticker[ticker] = calc_atr(rec["h"], rec["l"], rec["c"])
                date_index_by_ticker[ticker] = {d: i for i, d in enumerate(rec["dates"])}

        rec = cache_by_ticker[ticker]
        if not rec:
            no_cache += 1
            trade["chandelier_exit_date"] = None
            trade["chandelier_exit_price"] = None
            trade["chandelier_return_pct"] = None
            trade["chandelier_days_held"] = None
            trade["chandelier_still_open"] = None
            trade["chandelier_discarded_discontinuity"] = None
            continue

        entry_idx = date_index_by_ticker[ticker].get(trade["entry_date"])
        if entry_idx is None:
            no_cache += 1
            trade["chandelier_exit_date"] = None
            trade["chandelier_exit_price"] = None
            trade["chandelier_return_pct"] = None
            trade["chandelier_days_held"] = None
            trade["chandelier_still_open"] = None
            trade["chandelier_discarded_discontinuity"] = None
            continue

        bad_set = set(rec.get("bad_indices", []))
        exit_idx, disc = simulate_chandelier(
            rec["h"], rec["l"], rec["c"], atr_by_ticker[ticker], entry_idx, bad_set
        )

        if disc:
            discarded += 1
            trade["chandelier_exit_date"] = None
            trade["chandelier_exit_price"] = None
            trade["chandelier_return_pct"] = None
            trade["chandelier_days_held"] = None
            trade["chandelier_still_open"] = False
            trade["chandelier_discarded_discontinuity"] = True
        elif exit_idx is None:
            still_open += 1
            trade["chandelier_exit_date"] = None
            trade["chandelier_exit_price"] = None
            trade["chandelier_return_pct"] = None
            trade["chandelier_days_held"] = None
            trade["chandelier_still_open"] = True
            trade["chandelier_discarded_discontinuity"] = False
        else:
            entry_price = trade["entry_price"]
            exit_price = rec["c"][exit_idx]
            return_pct = ((exit_price / entry_price) - 1) * 100 if entry_price else None
            trade["chandelier_exit_date"] = rec["dates"][exit_idx]
            trade["chandelier_exit_price"] = round(exit_price, 4)
            trade["chandelier_return_pct"] = round(return_pct, 2) if return_pct is not None else None
            trade["chandelier_days_held"] = exit_idx - entry_idx
            trade["chandelier_still_open"] = False
            trade["chandelier_discarded_discontinuity"] = False
            added += 1

    dataset["chandelier_atr_multiplier"] = ATR_MULTIPLIER
    dataset["chandelier_note"] = (
        "Simulazione parallela: stesso ingresso BUY1/BUY2/BUY3 del trade originale, ma "
        "uscita via Chandelier Exit (trailing stop = massimo dall'ingresso - 3xATR14) "
        "invece che SAR flip down. chandelier_still_open=true significa che lo stop non "
        "è mai scattato entro la fine dello storico disponibile (non è un'uscita mancata, "
        "è che la posizione sarebbe ancora aperta oggi)."
    )

    with open(TRADES_PATH, "w", encoding="utf-8") as f:
        json.dump(sanitize_nan(dataset), f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    print(f"\nCompletato: {added} uscite Chandelier calcolate")
    print(f"  Ancora aperte (stop mai raggiunto): {still_open}")
    print(f"  Scartate per discontinuità: {discarded}")
    print(f"  Senza cache/data mismatch: {no_cache}")


if __name__ == "__main__":
    main()
