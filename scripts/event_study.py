#!/usr/bin/env python3
"""event_study.py

Event study su 6 indicatori singoli (non trade completi entrata->uscita):
SAR flip UP/DOWN, AO in crescita/decrescita per 2 barre, prezzo che
attraversa KAMA al rialzo/ribasso. Per ogni occorrenza dell'evento,
misura il rendimento del prezzo a +5/+10/+20 giorni di borsa dopo.

Legge SOLO la cache locale prodotta da fetch_raw_prices.py
(data/raw_prices/*.json) — NESSUNA chiamata a yfinance qui. Questo è
il punto dell'architettura a due fasi: il fetch (lento, costoso in
tempo/rate-limit) si fa una volta sola; gli esperimenti di event study
(questo script) girano in secondi/minuti in locale, ripetibili quante
volte serve senza mai ritoccare yfinance.

Output: data/event_study.json — per ciascuno dei 6 eventi:
- aggregato sull'intero universo (win rate + rendimento medio per orizzonte)
- aggregato per categoria (asset_class / leva vs lineare)
- per singolo ticker (con conteggio occorrenze, per poter filtrare il
  rumore statistico dei ticker con pochissime occorrenze)
"""

import json
import os
import glob
import datetime

RAW_DIR_NAME = "raw_prices"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", RAW_DIR_NAME)
OUT_PATH = os.path.join(BASE_DIR, "data", "event_study.json")

HORIZONS = (5, 10, 20)


# ═══════════════════════════════════════════════════════
#  INDICATORI — stessa logica di calculate_scores.py/generate_charts.py
# ═══════════════════════════════════════════════════════

def calc_kama(close, n=10, fast=2, slow=30):
    fast_sc = 2 / (fast + 1)
    slow_sc = 2 / (slow + 1)
    kama = [None] * len(close)
    if len(close) <= n:
        return kama
    kama[n] = close[n]
    for i in range(n + 1, len(close)):
        direction = abs(close[i] - close[i - n])
        volatility = sum(abs(close[j] - close[j - 1]) for j in range(i - n + 1, i + 1))
        er = direction / volatility if volatility != 0 else 0
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        kama[i] = kama[i - 1] + sc * (close[i] - kama[i - 1])
    return kama


def calc_sar_array(high, low, af0=0.02, af_max=0.20):
    n = len(high)
    bull_arr = [None] * n
    if n < 5:
        return bull_arr
    sar = low[0]
    ep = high[0]
    af = af0
    bull = True
    bull_arr[0] = bull
    for i in range(1, n):
        if bull:
            new_sar = sar + af * (ep - sar)
            new_sar = min(new_sar, low[max(0, i - 1)], low[max(0, i - 2)])
            if low[i] < new_sar:
                bull = False
                new_sar = ep
                ep = low[i]
                af = af0
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af0, af_max)
        else:
            new_sar = sar + af * (ep - sar)
            new_sar = max(new_sar, high[max(0, i - 1)], high[max(0, i - 2)])
            if high[i] > new_sar:
                bull = True
                new_sar = ep
                ep = high[i]
                af = af0
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af0, af_max)
        sar = new_sar
        bull_arr[i] = bull
    return bull_arr


def calc_ao_array(high, low):
    mid = [(h + l) / 2 for h, l in zip(high, low)]
    result = [None] * len(mid)
    for i in range(33, len(mid)):
        sma5 = sum(mid[i - 4:i + 1]) / 5
        sma34 = sum(mid[i - 33:i + 1]) / 34
        result[i] = round(sma5 - sma34, 4)
    return result


# ═══════════════════════════════════════════════════════
#  RILEVAMENTO EVENTI — un indice per ogni occorrenza
# ═══════════════════════════════════════════════════════

def detect_events(closes, highs, lows, kama, sar_bull, ao):
    n = len(closes)
    events = {"sar_up": [], "sar_down": [], "ao_rising": [], "ao_falling": [],
              "kama_cross_up": [], "kama_cross_down": []}

    for i in range(1, n):
        if sar_bull[i] is not None and sar_bull[i - 1] is not None:
            if sar_bull[i] and not sar_bull[i - 1]:
                events["sar_up"].append(i)
            elif not sar_bull[i] and sar_bull[i - 1]:
                events["sar_down"].append(i)

        if kama[i] is not None and kama[i - 1] is not None:
            if closes[i - 1] <= kama[i - 1] and closes[i] > kama[i]:
                events["kama_cross_up"].append(i)
            elif closes[i - 1] >= kama[i - 1] and closes[i] < kama[i]:
                events["kama_cross_down"].append(i)

    for i in range(2, n):
        if ao[i] is not None and ao[i - 1] is not None and ao[i - 2] is not None:
            if ao[i] > ao[i - 1] > ao[i - 2]:
                events["ao_rising"].append(i)
            elif ao[i] < ao[i - 1] < ao[i - 2]:
                events["ao_falling"].append(i)

    return events


def window_crosses_discontinuity(entry_idx, exit_idx, bad_indices_set):
    return any(entry_idx < b <= exit_idx for b in bad_indices_set)


def measure_forward_returns(closes, event_indices, bad_indices, horizons=HORIZONS):
    """Per ogni occorrenza dell'evento, rendimento a +H giorni di borsa.
    Scarta le finestre che attraversano una discontinuità di prezzo nota."""
    bad_set = set(bad_indices)
    n = len(closes)
    results = []
    for i in event_indices:
        entry_price = closes[i]
        if not entry_price:
            continue
        per_horizon = {}
        for h in horizons:
            j = i + h
            if j >= n:
                continue
            if window_crosses_discontinuity(i, j, bad_set):
                continue
            per_horizon[h] = round((closes[j] / entry_price - 1) * 100, 3)
        if per_horizon:
            results.append({"idx": i, "returns": per_horizon})
    return results


def aggregate_returns(occurrences, horizons=HORIZONS):
    """occurrences: lista di {'idx':.., 'returns': {5: pct, 10: pct, ...}}"""
    agg = {}
    for h in horizons:
        vals = [o["returns"][h] for o in occurrences if h in o["returns"]]
        if vals:
            wins = sum(1 for v in vals if v > 0)
            agg[str(h)] = {
                "n": len(vals),
                "win_rate": round(wins / len(vals) * 100, 1),
                "avg_return_pct": round(sum(vals) / len(vals), 3),
            }
        else:
            agg[str(h)] = {"n": 0, "win_rate": None, "avg_return_pct": None}
    return agg


def category_key(asset_class, is_leveraged):
    if is_leveraged:
        return f"{asset_class}_leva"
    return asset_class


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"event_study.py — {now.isoformat()}")

    index_path = os.path.join(RAW_DIR, "index.json")
    if not os.path.exists(index_path):
        print(f"[ERROR] {index_path} non trovato — esegui prima fetch_raw_prices.py")
        return

    with open(index_path, "r", encoding="utf-8") as f:
        raw_index = json.load(f)

    files = raw_index.get("index", [])
    print(f"Cache prezzi disponibile: {len(files)} strumenti")

    EVENT_TYPES = ["sar_up", "sar_down", "ao_rising", "ao_falling", "kama_cross_up", "kama_cross_down"]

    # Accumulatori: per evento -> lista di occorrenze globali (per aggregato universo)
    #                          -> per categoria -> lista occorrenze
    #                          -> per ticker -> lista occorrenze
    global_occ = {e: [] for e in EVENT_TYPES}
    category_occ = {e: {} for e in EVENT_TYPES}
    ticker_occ = {e: {} for e in EVENT_TYPES}

    processed = 0
    for entry in files:
        fpath = os.path.join(RAW_DIR, entry["file"])
        if not os.path.exists(fpath):
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            rec = json.load(f)

        closes = rec["c"]
        highs = rec["h"]
        lows = rec["l"]
        bad_indices = rec.get("bad_indices", [])
        ticker = rec["ticker"]
        asset_class = entry.get("asset_class") or "unknown"
        is_leveraged = entry.get("is_leveraged", False)
        cat = category_key(asset_class, is_leveraged)

        kama = calc_kama(closes)
        sar_bull = calc_sar_array(highs, lows)
        ao = calc_ao_array(highs, lows)

        events = detect_events(closes, highs, lows, kama, sar_bull, ao)

        for etype in EVENT_TYPES:
            occ = measure_forward_returns(closes, events[etype], bad_indices)
            if not occ:
                continue
            global_occ[etype].extend(occ)
            category_occ[etype].setdefault(cat, []).extend(occ)
            ticker_occ[etype].setdefault(ticker, []).extend(occ)

        processed += 1
        if processed % 200 == 0:
            print(f"  {processed}/{len(files)} strumenti processati")

    print(f"\nProcessati {processed} strumenti dalla cache. Aggregazione risultati...")

    output_events = {}
    for etype in EVENT_TYPES:
        aggregate = aggregate_returns(global_occ[etype])
        by_category = {cat: aggregate_returns(occ) for cat, occ in category_occ[etype].items()}
        by_ticker = []
        for ticker, occ in ticker_occ[etype].items():
            stats = aggregate_returns(occ)
            n_total = len(occ)
            by_ticker.append({"ticker": ticker, "n_occurrences": n_total, **stats})
        by_ticker.sort(key=lambda x: x["n_occurrences"], reverse=True)

        output_events[etype] = {
            "total_occurrences": len(global_occ[etype]),
            "aggregate": aggregate,
            "by_category": by_category,
            "by_ticker": by_ticker,
        }

    output = {
        "generated_at": now.isoformat(),
        "horizons_trading_days": list(HORIZONS),
        "instruments_processed": processed,
        "note": (
            "Event study su indicatori singoli (non trade completi). Rendimento "
            "misurato a N giorni di borsa dopo l'evento, finestre che attraversano "
            "una discontinuità di prezzo nota vengono scartate. by_ticker include "
            "n_occurrences: con pochi casi il win rate è statisticamente poco "
            "affidabile, filtrare per soglia minima in fase di analisi."
        ),
        "events": output_events,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    print(f"\nCompletato: risultati salvati in data/event_study.json")
    for etype in EVENT_TYPES:
        print(f"  {etype}: {output_events[etype]['total_occurrences']} occorrenze")


if __name__ == "__main__":
    main()
