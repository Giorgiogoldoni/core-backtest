#!/usr/bin/env python3
"""confluence_study.py

Come event_study.py, ma invece di 6 indicatori isolati testa 3
COMBINAZIONI (confluenza di più condizioni nello stesso momento) — per
capire se unire condizioni recupera l'edge che i singoli indicatori,
presi da soli, non avevano (vedi event_study.json: eccesso quasi nullo
o negativo su tutti e 6 gli eventi isolati).

Combinazioni testate:
  sar_ao       = SAR flip UP + AO in crescita da 2 barre nello stesso momento
  sar_kama     = SAR flip UP + prezzo già sopra KAMA
  ao_kama      = AO in crescita da 2 barre + prezzo sopra KAMA

Legge SOLO la cache locale (data/raw_prices/*.json) — NESSUNA chiamata
a yfinance. Stessa metodologia di event_study.py: rendimento a
+5/+10/+20 giorni di borsa, baseline per strumento (rendimento medio
su TUTTI i giorni) ed eccesso rispetto al baseline — senza il quale un
rendimento positivo può riflettere solo il drift generale di mercato,
non un vero effetto della combinazione.

Output: data/confluence_study.json
"""

import json
import os
import datetime
import math

RAW_DIR_NAME = "raw_prices"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", RAW_DIR_NAME)
OUT_PATH = os.path.join(BASE_DIR, "data", "confluence_study.json")

HORIZONS = (5, 10, 20)

COMBO_TYPES = ["sar_ao", "sar_kama", "ao_kama"]
COMBO_LABELS = {
    "sar_ao": "SAR Flip UP + AO in crescita",
    "sar_kama": "SAR Flip UP + Prezzo sopra KAMA",
    "ao_kama": "AO in crescita + Prezzo sopra KAMA",
}


# ═══════════════════════════════════════════════════════
#  INDICATORI — stessa logica di event_study.py
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
#  RILEVAMENTO CONFLUENZE
# ═══════════════════════════════════════════════════════

def detect_confluences(closes, kama, sar_bull, ao):
    n = len(closes)
    events = {c: [] for c in COMBO_TYPES}

    for i in range(2, n):
        if sar_bull[i] is None or sar_bull[i - 1] is None:
            continue
        sar_flip_up = sar_bull[i] and not sar_bull[i - 1]

        ao_rising = (ao[i] is not None and ao[i - 1] is not None and ao[i - 2] is not None
                     and ao[i] > ao[i - 1] > ao[i - 2])

        above_kama = kama[i] is not None and closes[i] > kama[i]

        if sar_flip_up and ao_rising:
            events["sar_ao"].append(i)
        if sar_flip_up and above_kama:
            events["sar_kama"].append(i)
        if ao_rising and above_kama:
            events["ao_kama"].append(i)

    return events


def window_crosses_discontinuity(entry_idx, exit_idx, bad_indices_set):
    return any(entry_idx < b <= exit_idx for b in bad_indices_set)


def measure_forward_returns(closes, event_indices, bad_indices, ticker, horizons=HORIZONS):
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
            results.append({"idx": i, "ticker": ticker, "returns": per_horizon})
    return results


def compute_baseline(closes, bad_indices, horizons=HORIZONS):
    bad_set = set(bad_indices)
    n = len(closes)
    baseline = {}
    for h in horizons:
        vals = []
        for i in range(n - h):
            entry_price = closes[i]
            if not entry_price:
                continue
            if window_crosses_discontinuity(i, i + h, bad_set):
                continue
            vals.append((closes[i + h] / entry_price - 1) * 100)
        baseline[h] = round(sum(vals) / len(vals), 3) if vals else None
    return baseline


def aggregate_returns(occurrences, baseline_by_ticker, horizons=HORIZONS):
    agg = {}
    for h in horizons:
        vals = [o["returns"][h] for o in occurrences if h in o["returns"]]
        baseline_vals = [
            baseline_by_ticker[o["ticker"]][h]
            for o in occurrences
            if h in o["returns"] and baseline_by_ticker.get(o["ticker"], {}).get(h) is not None
        ]
        if vals:
            wins = sum(1 for v in vals if v > 0)
            avg_return = sum(vals) / len(vals)
            avg_baseline = sum(baseline_vals) / len(baseline_vals) if baseline_vals else None
            agg[str(h)] = {
                "n": len(vals),
                "win_rate": round(wins / len(vals) * 100, 1),
                "avg_return_pct": round(avg_return, 3),
                "baseline_avg_return_pct": round(avg_baseline, 3) if avg_baseline is not None else None,
                "excess_return_pct": round(avg_return - avg_baseline, 3) if avg_baseline is not None else None,
            }
        else:
            agg[str(h)] = {"n": 0, "win_rate": None, "avg_return_pct": None,
                            "baseline_avg_return_pct": None, "excess_return_pct": None}
    return agg


def category_key(asset_class, is_leveraged):
    return f"{asset_class}_leva" if is_leveraged else asset_class


def sanitize_nan(obj):
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_nan(v) for v in obj]
    return obj


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"confluence_study.py — {now.isoformat()}")

    index_path = os.path.join(RAW_DIR, "index.json")
    if not os.path.exists(index_path):
        print(f"[ERROR] {index_path} non trovato — esegui prima fetch_raw_prices.py")
        return

    with open(index_path, "r", encoding="utf-8") as f:
        raw_index = json.load(f)

    files = raw_index.get("index", [])
    print(f"Cache prezzi disponibile: {len(files)} strumenti")

    global_occ = {c: [] for c in COMBO_TYPES}
    category_occ = {c: {} for c in COMBO_TYPES}
    ticker_occ = {c: {} for c in COMBO_TYPES}
    baseline_by_ticker = {}

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

        confluences = detect_confluences(closes, kama, sar_bull, ao)
        baseline_by_ticker[ticker] = compute_baseline(closes, bad_indices)

        for ctype in COMBO_TYPES:
            occ = measure_forward_returns(closes, confluences[ctype], bad_indices, ticker)
            if not occ:
                continue
            global_occ[ctype].extend(occ)
            category_occ[ctype].setdefault(cat, []).extend(occ)
            ticker_occ[ctype].setdefault(ticker, []).extend(occ)

        processed += 1
        if processed % 200 == 0:
            print(f"  {processed}/{len(files)} strumenti processati")

    print(f"\nProcessati {processed} strumenti dalla cache. Aggregazione risultati...")

    output_combos = {}
    for ctype in COMBO_TYPES:
        aggregate = aggregate_returns(global_occ[ctype], baseline_by_ticker)
        by_category = {cat: aggregate_returns(occ, baseline_by_ticker) for cat, occ in category_occ[ctype].items()}
        by_ticker = []
        for ticker, occ in ticker_occ[ctype].items():
            stats = aggregate_returns(occ, baseline_by_ticker)
            by_ticker.append({"ticker": ticker, "n_occurrences": len(occ), **stats})
        by_ticker.sort(key=lambda x: x["n_occurrences"], reverse=True)

        output_combos[ctype] = {
            "label": COMBO_LABELS[ctype],
            "total_occurrences": len(global_occ[ctype]),
            "aggregate": aggregate,
            "by_category": by_category,
            "by_ticker": by_ticker,
        }

    output = {
        "generated_at": now.isoformat(),
        "horizons_trading_days": list(HORIZONS),
        "instruments_processed": processed,
        "note": (
            "Event study su CONFLUENZE (combinazioni di 2 condizioni nello stesso momento), "
            "non indicatori isolati — vedi event_study.json per il confronto con i singoli. "
            "baseline_avg_return_pct e excess_return_pct hanno lo stesso significato: "
            "l'eccesso rispetto al rendimento medio dello strumento su tutti i giorni è "
            "l'unica metrica che indica un vero effetto, non il drift generale di mercato."
        ),
        "combos": output_combos,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(sanitize_nan(output), f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    print(f"\nCompletato: risultati salvati in data/confluence_study.json")
    for ctype in COMBO_TYPES:
        print(f"  {ctype}: {output_combos[ctype]['total_occurrences']} occorrenze")


if __name__ == "__main__":
    main()
