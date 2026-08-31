#!/usr/bin/env python3
"""rev1_exit_comparison.py

Sugli STESSI ingressi REV1 (RSI<35 + AO in miglioramento), simula in
PARALLELO 4 regole di uscita candidate — non sequenziali, non legate a
uno stato di posizione condiviso: ogni uscita è simulata
indipendentemente dallo stesso punto di ingresso, per un confronto
pulito a parità di punto di partenza.

Candidati (parametri di default, NON ANCORA VALIDATI fuori campione —
solo il vincitore verrà sottoposto alla stessa validazione seria già
fatta per la soglia d'ingresso, per non raddoppiare il lavoro su
candidati che potrebbero perdere comunque):

  rsi_recover  = esce quando RSI(14) torna sopra 60 (simmetrico
                 all'ingresso: sei entrato su RSI basso, esci quando
                 torna "normale/alto")
  fixed_target = esce al primo giorno in cui il rendimento raggiunge +5%
  time_stop    = esce comunque dopo 15 giorni di borsa, a prescindere
  chandelier   = trailing stop 3xATR14 (riuso identico allo script
                 add_chandelier_exit.py) — outsider concettuale: pensato
                 per trend-following, REV1 è mean-reversion, testato
                 comunque per completezza empirica, non per favoritismo

Per ciascuno: media, MEDIANA (non solo la media — lezione imparata dal
confronto Chandelier sul motore attuale, dove la media era gonfiata da
pochi outlier mentre la mediana era negativa), eccesso vs baseline a
parità di durata, % che batte il baseline.

Legge SOLO la cache locale (data/raw_prices/*.json) — NESSUNA chiamata
a yfinance.

Output: data/rev1_exit_comparison.json
"""

import json
import os
import datetime
import math

RAW_DIR_NAME = "raw_prices"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", RAW_DIR_NAME)
OUT_PATH = os.path.join(BASE_DIR, "data", "rev1_exit_comparison.json")

RSI_ENTRY_THRESHOLD = 35   # soglia d'ingresso REV1 già validata fuori campione
RSI_RECOVER_THRESHOLD = 60  # candidato uscita 1 — default, non ancora validato
FIXED_TARGET_PCT = 5.0      # candidato uscita 2 — default, non ancora validato
TIME_STOP_DAYS = 15         # candidato uscita 3 — default, non ancora validato
CHANDELIER_ATR_MULTIPLIER = 3

EXIT_TYPES = ["rsi_recover", "fixed_target", "time_stop", "chandelier"]
EXIT_LABELS = {
    "rsi_recover": f"RSI(14) torna sopra {RSI_RECOVER_THRESHOLD}",
    "fixed_target": f"Target fisso +{FIXED_TARGET_PCT}%",
    "time_stop": f"Time stop {TIME_STOP_DAYS} giorni",
    "chandelier": f"Chandelier Exit ({CHANDELIER_ATR_MULTIPLIER}xATR14)",
}


# ═══════════════════════════════════════════════════════
#  INDICATORI
# ═══════════════════════════════════════════════════════

def calc_ao_array(high, low):
    mid = [(h + l) / 2 for h, l in zip(high, low)]
    result = [None] * len(mid)
    for i in range(33, len(mid)):
        sma5 = sum(mid[i - 4:i + 1]) / 5
        sma34 = sum(mid[i - 33:i + 1]) / 34
        result[i] = round(sma5 - sma34, 4)
    return result


def calc_rsi_array(close, n=14):
    result = [None] * len(close)
    if len(close) < n + 2:
        return result
    for i in range(n, len(close)):
        gains = 0.0
        losses = 0.0
        for j in range(i - n + 1, i + 1):
            d = close[j] - close[j - 1]
            if d > 0:
                gains += d
            else:
                losses += -d
        ag = gains / n
        al = losses / n
        result[i] = round(100 - 100 / (1 + ag / al), 2) if al > 0 else 100.0
    return result


def calc_atr(high, low, close, n=14):
    trs = []
    for i in range(len(close)):
        if i == 0:
            trs.append(high[i] - low[i])
        else:
            trs.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    atr_arr = [None] * n
    if len(trs) < n + 1:
        return [None] * len(close)
    atr = sum(trs[1:n + 1]) / n
    atr_arr.append(atr)
    for i in range(n + 1, len(trs)):
        atr = (atr * (n - 1) + trs[i]) / n
        atr_arr.append(atr)
    while len(atr_arr) < len(close):
        atr_arr.append(atr_arr[-1])
    return atr_arr[:len(close)]


def window_crosses_discontinuity(entry_idx, exit_idx, bad_indices_set):
    return any(entry_idx < b <= exit_idx for b in bad_indices_set)


# ═══════════════════════════════════════════════════════
#  RILEVAMENTO INGRESSI REV1 (fresh signal, no gating su posizione —
#  qui testiamo 4 uscite indipendenti sullo stesso punto di partenza,
#  non simuliamo un portafoglio reale con una sola posizione aperta)
# ═══════════════════════════════════════════════════════

def detect_rev1_entries(rsi14, ao):
    n = len(rsi14)
    entries = []
    prev_ok = False
    for i in range(2, n):
        ok = (rsi14[i] is not None and rsi14[i] < RSI_ENTRY_THRESHOLD
              and ao[i] is not None and ao[i - 1] is not None and ao[i] > ao[i - 1])
        if ok and not prev_ok:
            entries.append(i)
        prev_ok = ok
    return entries


# ═══════════════════════════════════════════════════════
#  SIMULAZIONE DELLE 4 USCITE, DALLO STESSO INGRESSO
# ═══════════════════════════════════════════════════════

def simulate_exits(entry_idx, closes, highs, lows, rsi14, atr_arr, bad_set):
    n = len(closes)
    entry_price = closes[entry_idx]
    results = {}

    # 1. RSI recovery
    exit_idx = None
    for j in range(entry_idx + 1, n):
        if j in bad_set:
            results["rsi_recover"] = {"discarded": True}
            break
        if rsi14[j] is not None and rsi14[j] >= RSI_RECOVER_THRESHOLD:
            exit_idx = j
            break
    else:
        if "rsi_recover" not in results:
            results["rsi_recover"] = {"still_open": True}
    if exit_idx is not None:
        results["rsi_recover"] = {"exit_idx": exit_idx}

    # 2. Fixed target
    exit_idx = None
    for j in range(entry_idx + 1, n):
        if j in bad_set:
            results["fixed_target"] = {"discarded": True}
            break
        ret = (closes[j] / entry_price - 1) * 100 if entry_price else None
        if ret is not None and ret >= FIXED_TARGET_PCT:
            exit_idx = j
            break
    else:
        if "fixed_target" not in results:
            results["fixed_target"] = {"still_open": True}
    if exit_idx is not None:
        results["fixed_target"] = {"exit_idx": exit_idx}

    # 3. Time stop (fisso, non dipende dal percorso — solo discontinuità nel mezzo)
    j = entry_idx + TIME_STOP_DAYS
    if j >= n:
        results["time_stop"] = {"still_open": True}
    elif window_crosses_discontinuity(entry_idx, j, bad_set):
        results["time_stop"] = {"discarded": True}
    else:
        results["time_stop"] = {"exit_idx": j}

    # 4. Chandelier (trailing stop 3xATR14)
    highest_high = highs[entry_idx]
    exit_idx = None
    discarded = False
    for j in range(entry_idx + 1, n):
        if j in bad_set:
            discarded = True
            break
        highest_high = max(highest_high, highs[j])
        atr_j = atr_arr[j]
        if atr_j is None:
            continue
        stop_level = highest_high - CHANDELIER_ATR_MULTIPLIER * atr_j
        if closes[j] < stop_level:
            exit_idx = j
            break
    if discarded:
        results["chandelier"] = {"discarded": True}
    elif exit_idx is not None:
        results["chandelier"] = {"exit_idx": exit_idx}
    else:
        results["chandelier"] = {"still_open": True}

    return results


def baseline_for_duration(closes, bad_indices_set, duration):
    n = len(closes)
    if duration <= 0 or duration >= n:
        return None
    vals = []
    for i in range(n - duration):
        p = closes[i]
        if not p:
            continue
        if window_crosses_discontinuity(i, i + duration, bad_indices_set):
            continue
        vals.append((closes[i + duration] / p - 1) * 100)
    return round(sum(vals) / len(vals), 3) if vals else None


def median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return None
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


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
    print(f"rev1_exit_comparison.py — {now.isoformat()}")

    index_path = os.path.join(RAW_DIR, "index.json")
    if not os.path.exists(index_path):
        print(f"[ERROR] {index_path} non trovato — esegui prima fetch_raw_prices.py")
        return

    with open(index_path, "r", encoding="utf-8") as f:
        raw_index = json.load(f)
    files = raw_index.get("index", [])
    print(f"Cache prezzi disponibile: {len(files)} strumenti")

    # Accumulatori per tipo di uscita: return_pct, days_held, excess
    exit_stats = {e: {"returns": [], "excess": []} for e in EXIT_TYPES}
    exit_counts = {e: {"n": 0, "still_open": 0, "discarded": 0} for e in EXIT_TYPES}

    baseline_cache = {}
    processed = 0
    total_entries = 0

    for entry in files:
        fpath = os.path.join(RAW_DIR, entry["file"])
        if not os.path.exists(fpath):
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            rec = json.load(f)

        ticker = rec["ticker"]
        closes, highs, lows = rec["c"], rec["h"], rec["l"]
        bad_indices = rec.get("bad_indices", [])
        bad_set = set(bad_indices)

        ao = calc_ao_array(highs, lows)
        rsi14 = calc_rsi_array(closes)
        atr_arr = calc_atr(highs, lows, closes, 14)

        entries = detect_rev1_entries(rsi14, ao)
        total_entries += len(entries)

        for entry_idx in entries:
            sims = simulate_exits(entry_idx, closes, highs, lows, rsi14, atr_arr, bad_set)
            entry_price = closes[entry_idx]

            for etype in EXIT_TYPES:
                sim = sims[etype]
                if sim.get("still_open"):
                    exit_counts[etype]["still_open"] += 1
                    continue
                if sim.get("discarded"):
                    exit_counts[etype]["discarded"] += 1
                    continue

                exit_idx = sim["exit_idx"]
                exit_price = closes[exit_idx]
                ret = ((exit_price / entry_price) - 1) * 100 if entry_price else None
                if ret is None:
                    continue

                duration = exit_idx - entry_idx
                key = (ticker, duration)
                if key not in baseline_cache:
                    baseline_cache[key] = baseline_for_duration(closes, bad_set, duration)
                baseline = baseline_cache[key]

                exit_stats[etype]["returns"].append(ret)
                if baseline is not None:
                    exit_stats[etype]["excess"].append(ret - baseline)
                exit_counts[etype]["n"] += 1

        processed += 1
        if processed % 200 == 0:
            print(f"  {processed}/{len(files)} strumenti processati")

    print(f"\nProcessati {processed} strumenti — {total_entries} ingressi REV1 rilevati")

    results = {}
    for etype in EXIT_TYPES:
        rets = exit_stats[etype]["returns"]
        excs = exit_stats[etype]["excess"]
        results[etype] = {
            "label": EXIT_LABELS[etype],
            "n": exit_counts[etype]["n"],
            "still_open": exit_counts[etype]["still_open"],
            "discarded_discontinuity": exit_counts[etype]["discarded"],
            "avg_return_pct": round(sum(rets) / len(rets), 3) if rets else None,
            "median_return_pct": round(median(rets), 3) if rets else None,
            "win_rate": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1) if rets else None,
            "avg_excess_return_pct": round(sum(excs) / len(excs), 3) if excs else None,
            "median_excess_return_pct": round(median(excs), 3) if excs else None,
            "pct_beats_baseline": round(sum(1 for e in excs if e > 0) / len(excs) * 100, 1) if excs else None,
        }
        print(f"\n{EXIT_LABELS[etype]}:")
        print(f"  n={exit_counts[etype]['n']}  media={results[etype]['avg_return_pct']}%  mediana={results[etype]['median_return_pct']}%")
        print(f"  eccesso medio={results[etype]['avg_excess_return_pct']}%  eccesso mediano={results[etype]['median_excess_return_pct']}%")

    output = {
        "generated_at": now.isoformat(),
        "instruments_processed": processed,
        "total_rev1_entries": total_entries,
        "rsi_entry_threshold": RSI_ENTRY_THRESHOLD,
        "note": (
            "4 uscite candidate simulate INDIPENDENTEMENTE dagli stessi ingressi REV1 "
            "(non sequenziali, non un portafoglio reale con una sola posizione aperta). "
            "Parametri di default NON ANCORA VALIDATI fuori campione — solo il vincitore "
            "verrà sottoposto alla stessa validazione seria già fatta per la soglia "
            "d'ingresso. Guardare SEMPRE mediana ed eccesso mediano insieme alla media: "
            "una media positiva con mediana negativa segnala risultato trainato da pochi "
            "outlier, non un miglioramento diffuso (lezione dal confronto Chandelier sul "
            "motore attuale)."
        ),
        "exits": results,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(sanitize_nan(output), f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    print(f"\nCompletato: risultati salvati in data/rev1_exit_comparison.json")


if __name__ == "__main__":
    main()
