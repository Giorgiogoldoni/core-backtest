#!/usr/bin/env python3
"""backtest_fetch.py

Genera un dataset di trade storici con esito noto, su TUTTO l'universo
core (non solo i qualificati BUY/WATCHLIST del giorno) — a differenza di
data/charts/*.json in core, che soffre di survivorship bias (contiene solo
gli strumenti "in forma" nel momento in cui viene generato). Qui si guarda
indietro nel tempo su ogni strumento indipendentemente dal suo stato oggi.

Ambito: esclude bond e money-market (motore trend-following pensato per
equity/leva/commodity/crypto; i money-market hanno trend liscio non
significativo, i bond restano fuori per scelta esplicita).

Profondità: fino a 3 anni per ticker (yfinance period='3y'), fallback
automatico sul massimo storico disponibile se lo strumento è più giovane.

Motore di segnale: IDENTICO a core/generate_charts.py (stesse funzioni
KAMA/SAR/AO/RSI/ER/Baffetti/segnale) per restare coerenti tra i due repo —
il dataset di trade deve riflettere lo stesso motore che genera i grafici.

Output: data/trades_dataset.json — lista di trade con feature allo
scattare dell'ingresso, esito (rendimento%, giorni), e conteggio dei
trade scartati per discontinuità di prezzo (rebase/split ETP non
allineati da Yahoo).

Solo generazione dataset in questo step — NIENTE training del modello qui.
"""

import json
import os
import time
import urllib.request
import datetime

import yfinance as yf

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BASE_DIR, "data", "trades_dataset.json")
UNIVERSE_URL = "https://raw.githubusercontent.com/Giorgiogoldoni/core/main/data/tickers_universe.json"

SLEEP_BETWEEN_TICKERS = 0.3
HISTORY_PERIOD = "3y"

# Soglia discontinuità di prezzo (rebase/split ETP non allineati da Yahoo) —
# stessa soglia usata in raptor-leva: rapporto giorno-su-giorno >2.5x o <0.4x
DISCONTINUITY_HIGH = 2.5
DISCONTINUITY_LOW = 0.4

BUY_TIERS = ("BUY1", "BUY2", "BUY3")
EXIT_TIERS = ("EXIT1", "EXIT2")


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
    return selected


# ═══════════════════════════════════════════════════════
#  INDICATORI — identici a core/scripts/generate_charts.py
#  (a sua volta portato da raptor-one/raptor_chart_fetch.py)
#  per restare coerenti tra i repo che condividono il motore di segnale.
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
    sar_arr = [None] * n
    bull_arr = [None] * n
    if n < 5:
        return sar_arr, bull_arr
    sar = low[0]
    ep = high[0]
    af = af0
    bull = True
    sar_arr[0] = round(sar, 4)
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
        sar_arr[i] = round(sar, 4)
        bull_arr[i] = bull
    return sar_arr, bull_arr


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


def calc_mm_align_array(close):
    n = len(close)
    result = [False] * n
    cum = [0.0] * (n + 1)
    for i in range(n):
        cum[i + 1] = cum[i] + close[i]

    def avg(i, w):
        return (cum[i + 1] - cum[i + 1 - w]) / w if i + 1 >= w else None

    for i in range(n):
        mm20, mm50, mm100 = avg(i, 20), avg(i, 50), avg(i, 100)
        if mm20 is not None and mm50 is not None and mm100 is not None:
            result[i] = close[i] > mm20 > mm50 > mm100
    return result


def calc_cross_days_array(close, kama):
    n = len(close)
    result = [999] * n
    last_flip = None
    prev_above = None
    for i in range(n):
        if kama[i] is None:
            continue
        above = close[i] > kama[i]
        if prev_above is None:
            prev_above = above
            last_flip = i
            result[i] = 0
            continue
        if above != prev_above:
            last_flip = i
            prev_above = above
        result[i] = i - last_flip
    return result


def calc_ao_improving_array(ao):
    n = len(ao)
    result = [False] * n
    for i in range(1, n):
        if ao[i] is not None and ao[i - 1] is not None and ao[i] > ao[i - 1]:
            result[i] = True
    return result


def calc_segnale_array(close, kama, er_arr, baff_arr, ao_imp_arr, sar_bull_arr, cross_arr, mm_arr, rsi_arr):
    n = len(close)
    result = [None] * n
    for i in range(n):
        if kama[i] is None or sar_bull_arr[i] is None:
            continue
        lk = kama[i]
        lc = close[i]
        above_kama = lc > lk if lk else False
        sar_bull = sar_bull_arr[i]
        cross = cross_arr[i]
        ao_imp = ao_imp_arr[i]
        baff = baff_arr[i]
        er = er_arr[i]
        mm_align = mm_arr[i]
        rsi = rsi_arr[i] if rsi_arr[i] is not None else 50
        if sar_bull and cross <= 3 and ao_imp:
            result[i] = "BUY1"
        elif above_kama and baff >= 2:
            result[i] = "BUY2"
        elif above_kama and er >= 0.50 and baff >= 3 and mm_align:
            result[i] = "BUY3"
        elif not above_kama and not sar_bull:
            result[i] = "EXIT2"
        elif not sar_bull:
            result[i] = "EXIT1"
        else:
            near_kama = abs(lc - lk) / lk < 0.03 if lk and lk > 0 else False
            if er < 0.30 and rsi < 30 and ao_imp and (near_kama or not above_kama):
                result[i] = "MEAN REV"
            else:
                result[i] = "WATCH"
    return result


def calc_atr(high, low, close, n=14):
    trs = []
    for i in range(len(close)):
        if i == 0:
            trs.append(high[i] - low[i])
        else:
            trs.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    if len(trs) < n + 1:
        return [None] * len(close)
    atr_arr = [None] * (n)
    atr = sum(trs[1:n + 1]) / n
    atr_arr.append(atr)
    for i in range(n + 1, len(trs)):
        atr = (atr * (n - 1) + trs[i]) / n
        atr_arr.append(atr)
    while len(atr_arr) < len(close):
        atr_arr.append(atr_arr[-1])
    return atr_arr[:len(close)]


# ═══════════════════════════════════════════════════════
#  FILTRO SANITÀ — discontinuità di prezzo (rebase/split ETP)
# ═══════════════════════════════════════════════════════

def find_discontinuities(closes):
    """Ritorna gli indici di barra dove il rapporto giorno-su-giorno è anomalo
    (>2.5x o <0.4x) — tipico di rebase/split ETP non allineati da Yahoo."""
    bad = set()
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if not prev:
            continue
        ratio = closes[i] / prev
        if ratio > DISCONTINUITY_HIGH or ratio < DISCONTINUITY_LOW:
            bad.add(i)
    return bad


def window_crosses_discontinuity(entry_idx, exit_idx, bad_indices):
    return any(entry_idx < b <= exit_idx for b in bad_indices)


# ═══════════════════════════════════════════════════════
#  ESTRAZIONE TRADE
# ═══════════════════════════════════════════════════════

def extract_trades(ticker_yf, dates, closes, seg_arr, er_arr, baff_arr, rsi_arr, ao_arr,
                    cross_arr, mm_arr, atr_arr, volumes, bad_indices):
    trades = []
    discarded = 0
    n = len(seg_arr)
    i = 0
    prev_seg = None
    vol_sma20 = [None] * n
    for idx in range(n):
        if idx >= 19:
            vol_sma20[idx] = sum(volumes[idx - 19:idx + 1]) / 20

    while i < n:
        seg = seg_arr[i]
        if seg in BUY_TIERS and seg != prev_seg:
            entry_idx = i
            entry_tier = seg
            exit_idx = None
            exit_tier = None
            j = i + 1
            while j < n:
                if seg_arr[j] in EXIT_TIERS:
                    exit_idx = j
                    exit_tier = seg_arr[j]
                    break
                j += 1

            if exit_idx is not None:
                if window_crosses_discontinuity(entry_idx, exit_idx, bad_indices):
                    discarded += 1
                    i = exit_idx + 1
                    prev_seg = exit_tier
                    continue

                entry_price = closes[entry_idx]
                exit_price = closes[exit_idx]
                return_pct = ((exit_price / entry_price) - 1) * 100 if entry_price else None
                vol_avg = vol_sma20[entry_idx]
                trades.append({
                    "ticker": ticker_yf,
                    "entry_date": dates[entry_idx],
                    "exit_date": dates[exit_idx],
                    "entry_tier": entry_tier,
                    "exit_tier": exit_tier,
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "return_pct": round(return_pct, 2) if return_pct is not None else None,
                    "days_held": exit_idx - entry_idx,
                    "is_open": False,
                    "features_at_entry": {
                        "er": er_arr[entry_idx],
                        "baff": baff_arr[entry_idx],
                        "rsi": rsi_arr[entry_idx] if rsi_arr[entry_idx] is not None else 50,
                        "ao": ao_arr[entry_idx] if ao_arr[entry_idx] is not None else 0,
                        "cross_days": cross_arr[entry_idx],
                        "mm_align": int(mm_arr[entry_idx]),
                        "atr_pct": (atr_arr[entry_idx] / entry_price * 100) if atr_arr[entry_idx] and entry_price else None,
                        "vol_ratio": (volumes[entry_idx] / vol_avg) if vol_avg else None,
                    },
                })
                i = exit_idx + 1
                prev_seg = exit_tier
                continue
            else:
                # Trade ancora aperto alla fine dello storico — non ha un esito noto,
                # non entra nel dataset di training (nessun target da imparare).
                i = n
                prev_seg = seg
                continue
        prev_seg = seg
        i += 1

    return trades, discarded


def process_ticker(ticker_yf):
    try:
        tk = yf.Ticker(ticker_yf)
        hist = tk.history(period=HISTORY_PERIOD, interval="1d", timeout=25)
        if hist.empty or len(hist) < 100:
            return [], 0, "dati insufficienti"

        highs = [round(float(x), 4) for x in hist["High"].values]
        lows = [round(float(x), 4) for x in hist["Low"].values]
        closes = [round(float(x), 4) for x in hist["Close"].values]
        volumes = [int(x) for x in hist["Volume"].values]
        dates = [ts.strftime("%Y-%m-%d") for ts in hist.index]

        bad_indices = find_discontinuities(closes)

        kama_arr = calc_kama(closes)
        sar_arr, sar_bull_arr = calc_sar_array(highs, lows)
        ao_arr = calc_ao_array(highs, lows)
        rsi_arr = calc_rsi_array(closes)
        er_arr = calc_er_array(closes)
        baff_arr = calc_baffetti_array(highs, lows)
        mm_arr = calc_mm_align_array(closes)
        cross_arr = calc_cross_days_array(closes, kama_arr)
        ao_imp_arr = calc_ao_improving_array(ao_arr)
        atr_arr = calc_atr(highs, lows, closes, 14)
        seg_arr = calc_segnale_array(closes, kama_arr, er_arr, baff_arr, ao_imp_arr, sar_bull_arr, cross_arr, mm_arr, rsi_arr)

        trades, discarded = extract_trades(
            ticker_yf, dates, closes, seg_arr, er_arr, baff_arr, rsi_arr, ao_arr,
            cross_arr, mm_arr, atr_arr, volumes, bad_indices
        )
        return trades, discarded, None
    except Exception as e:
        return [], 0, str(e)


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"backtest_fetch.py — {now.isoformat()}")
    instruments = fetch_universe()

    all_trades = []
    total_discarded = 0
    errors = 0
    for idx, item in enumerate(instruments):
        ticker = item["ticker_yf"]
        trades, discarded, err = process_ticker(ticker)
        all_trades.extend(trades)
        total_discarded += discarded
        if err:
            errors += 1
        if (idx + 1) % 100 == 0:
            print(f"  {idx + 1}/{len(instruments)} — trade raccolti: {len(all_trades)}, scartati per discontinuità: {total_discarded}, errori: {errors}")
        time.sleep(SLEEP_BETWEEN_TICKERS)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    output = {
        "generated_at": now.isoformat(),
        "history_period": HISTORY_PERIOD,
        "instruments_scanned": len(instruments),
        "trades_count": len(all_trades),
        "trades_discarded_discontinuity": total_discarded,
        "fetch_errors": errors,
        "excluded_asset_classes": ["bond", "money_market"],
        "note": "Dataset di trade storici con esito noto (entry->exit completi). Solo generazione dati — nessun training del modello in questo step.",
        "trades": all_trades,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nCompletato: {len(all_trades)} trade salvati in data/trades_dataset.json")
    print(f"Scartati per discontinuità: {total_discarded} — errori fetch: {errors}/{len(instruments)}")


if __name__ == "__main__":
    main()
