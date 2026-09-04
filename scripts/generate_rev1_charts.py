#!/usr/bin/env python3
"""generate_rev1_charts.py

Genera data/charts/{TICKER}.json nello STESSO schema usato dal widget
grafico standard "scannerv3" (chart_widget.js, condiviso con i repo
etp/raptor-leva/raptor-one/core) — così i trade REV1 si possono
ispezionare visivamente con lo stesso grafico già in uso altrove.

IMPORTANTE — output minimale: il widget ha un fallback automatico lato
browser (se non trova gli array precalcolati come kama_d/sar_d/ecc.,
li ricalcola da solo dai soli prezzi grezzi 'd'). Qui quindi NON si
ricalcola nulla lato Python — si esporta solo OHLCV, molto più leggero
che duplicare tutta la logica indicatori (e soprattutto: non duplica
il peso della cache prezzi già presente in data/raw_prices/).

SCOPE LIMITATO: solo i 60 ticker con più trade REV1 (non tutto
l'universo — genererebbe ~140MB, raddoppiando il peso del repo per
duplicare dati già presenti in data/raw_prices/). Campione comunque
ampio per verificare visivamente se il sistema si comporta bene.

Legge SOLO la cache locale — NESSUNA chiamata a yfinance.
"""

import json
import os
import datetime
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw_prices")
TRADES_PATH = os.path.join(BASE_DIR, "data", "rev1_trades.json")
CHARTS_DIR = os.path.join(BASE_DIR, "data", "charts")

TOP_N_TICKERS = 60


def select_tickers():
    if not os.path.exists(TRADES_PATH):
        print(f"[ERROR] {TRADES_PATH} non trovato — esegui prima rev1_backtest.py")
        return []
    with open(TRADES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    counts = Counter(t["ticker"] for t in data.get("trades", []))
    top = [t for t, _ in counts.most_common(TOP_N_TICKERS)]
    return top


def process_ticker(ticker):
    fname = ticker.replace(".", "_") + ".json"
    fpath = os.path.join(RAW_DIR, fname)
    if not os.path.exists(fpath):
        return None
    with open(fpath, "r", encoding="utf-8") as f:
        rec = json.load(f)

    dates = rec["dates"]
    opens = rec.get("o", rec["c"])
    highs, lows, closes, vols = rec["h"], rec["l"], rec["c"], rec["v"]
    if len(closes) < 60:
        return None

    ts = [int(datetime.datetime.strptime(d, "%Y-%m-%d").timestamp()) for d in dates]
    d_bars = [[ts[i], opens[i], highs[i], lows[i], closes[i], vols[i]] for i in range(len(closes))]

    return {"ticker": ticker.split(".")[0], "yahoo": ticker, "d": d_bars, "h": []}


def main():
    tickers = select_tickers()
    print(f"Ticker selezionati (top {TOP_N_TICKERS} per numero di trade REV1): {len(tickers)}")

    os.makedirs(CHARTS_DIR, exist_ok=True)
    ok = 0
    errors = 0
    index = []
    for t in tickers:
        result = process_ticker(t)
        if result:
            fname = t.replace(".", "_") + ".json"
            with open(os.path.join(CHARTS_DIR, fname), "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
            index.append({"t": t.split(".")[0], "y": t, "f": fname})
            ok += 1
        else:
            errors += 1

    meta = {"ok": ok, "errors": errors, "index": index,
            "note": f"Campione dei {TOP_N_TICKERS} ticker con più trade REV1 (non tutto l'universo)."}
    with open(os.path.join(CHARTS_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Salvati {ok} file in data/charts/ — {errors} errori")


if __name__ == "__main__":
    main()
