#!/usr/bin/env python3
"""fetch_raw_prices.py

Scarica e mette in cache i prezzi grezzi (OHLCV, 3 anni) per tutto
l'universo core (escl. bond/money-market) — UNA volta sola. Gli event
study su singoli indicatori (SAR flip, AO in crescita/decrescita,
cross KAMA, e qualunque altro in futuro) si calcolano poi IN LOCALE su
questi dati cache, senza mai tornare a interrogare yfinance.

Perché separato da backtest_fetch.py: quello script fa fetch+calcolo
segnali in un unico passaggio, pensato per il dataset di trade completi
(entrata→uscita). Qui invece l'obiettivo è testare indicatori singoli,
che richiedono più varianti/esperimenti — rifare il fetch da yfinance
per ogni esperimento sarebbe lento (40-70 min a run) e rischioso
(più chiamate = più probabilità di rate-limit Yahoo). Con la cache,
ogni nuovo esperimento gira in secondi/minuti, in locale.

Output: data/raw_prices/{TICKER_SAFE}.json per ogni strumento (date,
OHLCV, indici di discontinuità di prezzo già precalcolati) +
data/raw_prices/index.json con l'elenco e le statistiche del fetch.
"""

import json
import os
import time
import urllib.request
import datetime
import math

import yfinance as yf

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, "data", "raw_prices")
UNIVERSE_URL = "https://raw.githubusercontent.com/Giorgiogoldoni/core/main/data/tickers_universe.json"

SLEEP_BETWEEN_TICKERS = 0.3
HISTORY_PERIOD = "3y"

# Stessa soglia di backtest_fetch.py e raptor-leva — rapporto giorno-su-giorno
# anomalo, tipico di rebase/split ETP non allineati da Yahoo. Precalcolata
# qui e salvata nella cache, così gli event study non la ricalcolano ogni volta.
DISCONTINUITY_HIGH = 2.5
DISCONTINUITY_LOW = 0.4


def fetch_universe():
    """Scarica l'universo live da core (non duplicato localmente, sempre aggiornato)."""
    with urllib.request.urlopen(UNIVERSE_URL, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    instruments = data.get("instruments", [])
    selected = [
        i for i in instruments
        if i.get("asset_class") != "bond" and not i.get("is_money_market", False)
    ]
    print(f"Universo core: {len(instruments)} totali -> {len(selected)} dopo esclusione bond/money-market")

    # LIMIT_TICKERS: variabile d'ambiente opzionale per un run di test su
    # campione ridotto. Campione CASUALE (non i primi N) — l'ordine di
    # tickers_universe.json non è casuale, segue il file sorgente Xetra.
    limit = os.environ.get("LIMIT_TICKERS")
    if limit:
        import random
        random.seed(42)
        n = min(int(limit), len(selected))
        selected = random.sample(selected, n)
        print(f"[TEST] Campione casuale di {len(selected)} strumenti (LIMIT_TICKERS={limit}, seed=42)")

    return selected


def find_discontinuities(closes):
    bad = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if not prev:
            continue
        ratio = closes[i] / prev
        if ratio > DISCONTINUITY_HIGH or ratio < DISCONTINUITY_LOW:
            bad.append(i)
    return bad


def sanitize_nan(obj):
    """NaN/Infinity sono validi in Python ma NON in JSON standard — JSON.parse()
    del browser (o un futuro script Node) fallirebbe in silenzio se il file
    li contiene. Sostituiti con null prima di scrivere."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_nan(v) for v in obj]
    return obj


def safe_filename(ticker_yf):
    return ticker_yf.replace(".", "_") + ".json"


def process_ticker(ticker_yf):
    try:
        tk = yf.Ticker(ticker_yf)
        hist = tk.history(period=HISTORY_PERIOD, interval="1d", timeout=25)
        if hist.empty or len(hist) < 100:
            return None, "dati insufficienti"

        # Scarta le barre con prezzi NaN (dati lacunosi yfinance) — un NaN a
        # metà serie contaminerebbe qualunque indicatore calcolato a valle
        # (cumulativo o con memoria, es. medie mobili) da quel punto in poi.
        hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
        if len(hist) < 100:
            return None, "dati insufficienti dopo pulizia NaN"

        opens = [round(float(x), 4) for x in hist["Open"].values]
        highs = [round(float(x), 4) for x in hist["High"].values]
        lows = [round(float(x), 4) for x in hist["Low"].values]
        closes = [round(float(x), 4) for x in hist["Close"].values]
        volumes = [int(x) for x in hist["Volume"].values]
        dates = [ts.strftime("%Y-%m-%d") for ts in hist.index]

        bad_indices = find_discontinuities(closes)

        record = {
            "ticker": ticker_yf,
            "dates": dates,
            "o": opens, "h": highs, "l": lows, "c": closes, "v": volumes,
            "bad_indices": bad_indices,
        }
        return sanitize_nan(record), None
    except Exception as e:
        return None, str(e)


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"fetch_raw_prices.py — {now.isoformat()}")
    instruments = fetch_universe()

    os.makedirs(OUT_DIR, exist_ok=True)

    ok = 0
    errors = 0
    index_entries = []
    for idx, item in enumerate(instruments):
        ticker = item["ticker_yf"]
        record, err = process_ticker(ticker)
        if record:
            fname = safe_filename(ticker)
            with open(os.path.join(OUT_DIR, fname), "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            index_entries.append({
                "ticker": ticker,
                "file": fname,
                "bars": len(record["dates"]),
                "first_date": record["dates"][0],
                "last_date": record["dates"][-1],
                "asset_class": item.get("asset_class"),
                "is_leveraged": item.get("is_leveraged", False),
            })
            ok += 1
        else:
            errors += 1
        if (idx + 1) % 100 == 0:
            print(f"  {idx + 1}/{len(instruments)} — ok: {ok}, errori: {errors}")
        time.sleep(SLEEP_BETWEEN_TICKERS)

    meta = {
        "generated_at": now.isoformat(),
        "history_period": HISTORY_PERIOD,
        "instruments_scanned": len(instruments),
        "ok": ok,
        "errors": errors,
        "excluded_asset_classes": ["bond", "money_market"],
        "note": "Cache prezzi grezzi (OHLCV) per event study locali su indicatori singoli — nessun ricalcolo yfinance necessario per nuovi esperimenti.",
        "index": index_entries,
    }
    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    print(f"\nCompletato: {ok} file salvati in data/raw_prices/ — {errors} errori su {len(instruments)}")


if __name__ == "__main__":
    main()
