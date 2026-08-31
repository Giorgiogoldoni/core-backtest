#!/usr/bin/env python3
"""rev1_backtest.py

REV1 — nuovo tier d'ingresso, nato dall'analisi per quintili di
analyze_features.py e VALIDATO fuori campione (soglia scelta su prima
metà storico, verificata su seconda metà mai vista: eccesso in-sample
+0.941%, out-of-sample +0.655%; anche la soglia standard RSI<30, non
scelta sui dati, tiene: +0.554% out-of-sample).

Regola d'ingresso REV1: RSI(14) < 35 + AO in miglioramento (ao[i] >
ao[i-1]) — CATTURA IL REBOUND, non il trend già confermato. A
differenza di BUY1/BUY2 (che richiedono prezzo sopra KAMA e momentum
già positivo), REV1 entra PRIMA della conferma di trend.

Regola d'uscita: RSI(14) torna sopra 60 — anch'essa VALIDATA fuori
campione (rev1_exit_comparison.py + out-of-sample: eccesso in-sample
+1.922%, out-of-sample +1.899%, tasso di posizioni mai risolte 2.6%,
detenzione media 14.5gg — scelta deliberatamente non aggressiva:
soglie più alte (70/80) mostravano eccesso apparente più alto ma
gonfiato da un tasso crescente di trade esclusi come "mai risolti",
stesso bias statistico scovato nel candidato "target fisso" scartato).
Confrontata con altri 3 candidati (target fisso +5% — scartato per
bias di selezione, time stop 15gg — solido ma inferiore, Chandelier
Exit 3xATR — bocciato: mediana negativa nonostante media positiva).

Legge SOLO la cache locale (data/raw_prices/*.json) — NESSUNA chiamata
a yfinance. Calcola anche baseline/eccesso per ogni trade nello stesso
passaggio (stessa metodologia di add_trade_benchmark.py: rendimento
medio dello stesso strumento su un periodo della stessa durata).

Output: data/rev1_trades.json
"""

import json
import os
import datetime
import math

RAW_DIR_NAME = "raw_prices"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "data", RAW_DIR_NAME)
OUT_PATH = os.path.join(BASE_DIR, "data", "rev1_trades.json")

RSI_ENTRY_THRESHOLD = 35    # soglia d'ingresso, validata fuori campione
RSI_EXIT_THRESHOLD = 60     # soglia d'uscita, validata fuori campione


# ═══════════════════════════════════════════════════════
#  INDICATORI — stessa logica degli altri script del repo
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


def calc_er_array(close, n=10):
    result = [0] * len(close)
    for i in range(n, len(close)):
        direction = abs(close[i] - close[i - n])
        volatility = sum(abs(close[j] - close[j - 1]) for j in range(i - n + 1, i + 1))
        result[i] = round(direction / volatility, 4) if volatility != 0 else 0
    return result


def calc_baffetti_array(high, low):
    mid = [(h + l) / 2 for h, l in zip(high, low)]
    result = [0] * len(mid)
    streak = 0
    for i in range(1, len(mid)):
        streak = streak + 1 if mid[i] > mid[i - 1] else 0
        result[i] = streak
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


# ═══════════════════════════════════════════════════════
#  RILEVAMENTO INGRESSO REV1 + USCITA (riuso SAR)
# ═══════════════════════════════════════════════════════

def window_crosses_discontinuity(entry_idx, exit_idx, bad_indices_set):
    return any(entry_idx < b <= exit_idx for b in bad_indices_set)


def extract_rev1_trades(dates, closes, rsi14, ao, er, baff, atr_arr, volumes, bad_indices):
    n = len(closes)
    bad_set = set(bad_indices)
    trades = []
    discarded = 0

    vol_sma20 = [None] * n
    for idx in range(n):
        if idx >= 19:
            vol_sma20[idx] = sum(volumes[idx - 19:idx + 1]) / 20

    in_position = False
    i = 0
    while i < n:
        if not in_position:
            entry_ok = (
                rsi14[i] is not None and rsi14[i] < RSI_ENTRY_THRESHOLD
                and ao[i] is not None and ao[i - 1] is not None and ao[i] > ao[i - 1]
            )
            if entry_ok:
                entry_idx = i
                # Cerca la prima barra successiva in cui l'RSI torna sopra la soglia d'uscita
                exit_idx = None
                j = i + 1
                while j < n:
                    if j in bad_set:
                        break  # discontinuità raggiunta prima di un'uscita chiara
                    if rsi14[j] is not None and rsi14[j] >= RSI_EXIT_THRESHOLD:
                        exit_idx = j
                        break
                    j += 1

                if exit_idx is not None:
                    if window_crosses_discontinuity(entry_idx, exit_idx, bad_set):
                        discarded += 1
                        i = exit_idx + 1
                        continue

                    entry_price = closes[entry_idx]
                    exit_price = closes[exit_idx]
                    return_pct = ((exit_price / entry_price) - 1) * 100 if entry_price else None
                    vol_avg = vol_sma20[entry_idx]

                    trades.append({
                        "entry_date": dates[entry_idx], "exit_date": dates[exit_idx],
                        "entry_tier": "REV1", "exit_tier": "RSI_RECOVER",
                        "entry_price": round(entry_price, 4), "exit_price": round(exit_price, 4),
                        "return_pct": round(return_pct, 2) if return_pct is not None else None,
                        "days_held": exit_idx - entry_idx, "is_open": False,
                        "features_at_entry": {
                            "rsi": rsi14[entry_idx], "ao": ao[entry_idx],
                            "er": er[entry_idx], "baff": baff[entry_idx],
                            "atr_pct": (atr_arr[entry_idx] / entry_price * 100) if atr_arr[entry_idx] and entry_price else None,
                            "vol_ratio": (volumes[entry_idx] / vol_avg) if vol_avg else None,
                        },
                    })
                    i = exit_idx + 1
                    continue
                else:
                    # Mai uscito entro fine storico — non ha esito noto, escluso dal dataset
                    i = n
                    continue
        i += 1

    return trades, discarded


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
    print(f"rev1_backtest.py — {now.isoformat()}")
    print(f"Soglia ingresso RSI: {RSI_ENTRY_THRESHOLD} — soglia uscita RSI: {RSI_EXIT_THRESHOLD} (entrambe validate fuori campione)")

    index_path = os.path.join(RAW_DIR, "index.json")
    if not os.path.exists(index_path):
        print(f"[ERROR] {index_path} non trovato — esegui prima fetch_raw_prices.py")
        return

    with open(index_path, "r", encoding="utf-8") as f:
        raw_index = json.load(f)
    files = raw_index.get("index", [])
    print(f"Cache prezzi disponibile: {len(files)} strumenti")

    all_trades = []
    total_discarded = 0
    baseline_cache = {}

    processed = 0
    for entry in files:
        fpath = os.path.join(RAW_DIR, entry["file"])
        if not os.path.exists(fpath):
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            rec = json.load(f)

        ticker = rec["ticker"]
        dates, closes, highs, lows, volumes = rec["dates"], rec["c"], rec["h"], rec["l"], rec["v"]
        bad_indices = rec.get("bad_indices", [])

        ao = calc_ao_array(highs, lows)
        rsi14 = calc_rsi_array(closes)
        er = calc_er_array(closes)
        baff = calc_baffetti_array(highs, lows)
        atr_arr = calc_atr(highs, lows, closes, 14)

        trades, discarded = extract_rev1_trades(
            dates, closes, rsi14, ao, er, baff, atr_arr, volumes, bad_indices
        )

        bad_set = set(bad_indices)
        for t in trades:
            dur = t["days_held"]
            key = (ticker, dur)
            if key not in baseline_cache:
                baseline_cache[key] = baseline_for_duration(closes, bad_set, dur)
            baseline = baseline_cache[key]
            t["ticker"] = ticker
            t["asset_class"] = entry.get("asset_class")
            t["is_leveraged"] = entry.get("is_leveraged", False)
            t["baseline_avg_return_pct"] = baseline
            t["excess_return_pct"] = round(t["return_pct"] - baseline, 3) if (baseline is not None and t["return_pct"] is not None) else None

        all_trades.extend(trades)
        total_discarded += discarded

        processed += 1
        if processed % 200 == 0:
            print(f"  {processed}/{len(files)} strumenti processati — trade raccolti: {len(all_trades)}")

    with_excess = [t for t in all_trades if t.get("excess_return_pct") is not None]
    avg_excess = sum(t["excess_return_pct"] for t in with_excess) / len(with_excess) if with_excess else None
    beat = sum(1 for t in with_excess if t["excess_return_pct"] > 0)

    output = {
        "generated_at": now.isoformat(),
        "rsi_entry_threshold": RSI_ENTRY_THRESHOLD,
        "rsi_exit_threshold": RSI_EXIT_THRESHOLD,
        "entry_rule": f"RSI(14) < {RSI_ENTRY_THRESHOLD} + AO in miglioramento (ao[i] > ao[i-1])",
        "exit_rule": f"RSI(14) torna sopra {RSI_EXIT_THRESHOLD} — validata fuori campione (eccesso out-of-sample +1.899%, tasso non risolti 2.6%)",
        "instruments_scanned": processed,
        "trades_count": len(all_trades),
        "trades_discarded_discontinuity": total_discarded,
        "avg_excess_return_pct": round(avg_excess, 3) if avg_excess is not None else None,
        "pct_beats_baseline": round(beat / len(with_excess) * 100, 1) if with_excess else None,
        "note": (
            "REV1: nuovo tier d'ingresso validato fuori campione (vedi commento in testa allo "
            "script). L'uscita riusa la logica SAR esistente (EXIT1/EXIT2) come scelta di "
            "partenza pragmatica — potrebbe non essere ottimale per un ingresso mean-reversion, "
            "da rivedere dopo aver visto questi risultati. excess_return_pct = return_pct meno "
            "il rendimento medio dello stesso strumento su un periodo della stessa durata "
            "(days_held), calcolato su tutti i punti di partenza possibili nello storico."
        ),
        "trades": all_trades,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(sanitize_nan(output), f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    print(f"\nCompletato: {len(all_trades)} trade REV1 salvati in data/rev1_trades.json")
    print(f"Scartati per discontinuità: {total_discarded}")
    if avg_excess is not None:
        print(f"Eccesso medio vs baseline: {avg_excess:+.3f}%")
        print(f"% trade che battono il baseline: {beat / len(with_excess) * 100:.1f}%")


if __name__ == "__main__":
    main()
