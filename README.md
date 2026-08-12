# core-backtest

Backtest storico dell'universo [core](https://github.com/Giorgiogoldoni/core), separato dalla pipeline giornaliera.

## Perché un repo separato

`core/data/charts/*.json` viene generato ogni giorno solo per gli strumenti
attualmente in BUY/WATCHLIST/ANTEPRIMA — un campione utile per consultazione,
ma **non adatto a costruire un dataset di training**: soffre di survivorship
bias (uno strumento che era BUY 6 mesi fa e oggi è NO TRADE non lascia
traccia del suo trade storico, vinto o perso che sia).

`core-backtest` guarda **indietro nel tempo su tutto l'universo**,
indipendentemente dallo stato di oggi, per costruire un dataset di trade
con esito noto — materiale per un futuro modello ML (non ancora allenato
in questo repo, solo generazione dati).

## Scope

- **Universo**: tutto `core`, **esclusi bond e money-market** (motore
  trend-following pensato per equity/leva/commodity/crypto)
- **Profondità**: fino a 3 anni per ticker (`yfinance period='3y'`),
  fallback automatico sul massimo storico disponibile se lo strumento è
  più giovane
- **Motore di segnale**: identico a `core/scripts/generate_charts.py`
  (stesse funzioni KAMA/SAR/AO/RSI/ER/Baffetti/segnale BUY1/BUY2/BUY3/
  EXIT1/EXIT2), per restare coerenti tra i due repo
- **Filtro sanità**: scarta i trade la cui finestra di valutazione
  attraversa un salto di prezzo anomalo (rapporto giorno-su-giorno >2.5x
  o <0.4x, tipico di rebase/split ETP non allineati da Yahoo) — stessa
  soglia già in uso su raptor-leva

## Output

`data/trades_dataset.json` — lista di trade completi (entrata→uscita,
con esito noto), ciascuno con le feature calcolate al momento
dell'ingresso (ER, Baffetti, RSI, AO, cross_days KAMA, allineamento
medie mobili, ATR%, rapporto volume). I trade ancora aperti a fine
storico **non** entrano nel dataset (nessun esito noto da imparare).

## Cadenza

Mensile (workflow_dispatch + cron il 1° del mese), non giornaliera —
il dataset storico non ha bisogno di aggiornamenti frequenti.

## Prossimi passi (non ancora fatti)

- Training di un modello (LightGBM/sklearn) sul dataset qui prodotto —
  in questo repo c'è solo la generazione dati, il training è un passo
  successivo separato
