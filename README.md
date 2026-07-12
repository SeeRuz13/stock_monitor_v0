# Stock Monitor

Monitora una watchlist di titoli/ETF: alert Telegram quando un titolo si muove oltre una soglia
percentuale rispetto all'apertura giornaliera, o quando l'algoritmo di trend rileva un'inversione.
Gira interamente su GitHub Actions (nessun PC/server da tenere acceso), con una dashboard
mobile-friendly su GitHub Pages per consultare lo stato quando vuoi.

## Setup (una tantum, ~15 minuti)

### 1. Crea il repository

Il repo deve essere **pubblico** (necessario per GitHub Pages gratuito). Non contiene dati
bancari/personali: solo la tua watchlist e gli ultimi prezzi/delta%.

```
cd stock-monitor
git init
git add .
git commit -m "setup"
git remote add origin https://github.com/TUO_USER/stock-monitor.git
git branch -M main
git push -u origin main
```

### 2. Crea il bot Telegram

1. Apri Telegram, cerca **@BotFather**, invia `/newbot` e segui le istruzioni (scegli nome e username).
2. BotFather ti da un **token** tipo `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` — copialo.
3. Cerca il tuo bot appena creato e mandagli un messaggio qualsiasi (es. "ciao"), altrimenti non puo' scriverti.
4. Recupera il tuo **chat_id**: apri nel browser
   `https://api.telegram.org/bot<IL_TUO_TOKEN>/getUpdates`
   e cerca il campo `"chat":{"id": ...}` nella risposta JSON.

### 3. Aggiungi i secrets su GitHub

Nel repo: **Settings → Secrets and variables → Actions → New repository secret**

- `TELEGRAM_BOT_TOKEN` — il token di BotFather
- `TELEGRAM_CHAT_ID` — il chat_id recuperato sopra

### 4. Abilita GitHub Pages

**Settings → Pages** → Source: "Deploy from a branch" → Branch: `main`, cartella `/docs` → Save.
Dopo qualche minuto la dashboard sara' visibile su `https://TUO_USER.github.io/stock-monitor/`.
Salvatela come collegamento nella home del telefono per accedervi come un'app.

### 5. Completa i due titoli con ISIN da verificare

In `watchlist.json` due voci sono disabilitate (`"enabled": false`) perche' l'ISIN fornito
non corrisponde in modo univoco a un fondo:

- **Amundi MSCI Asia** (ISIN `LU190068161` — mancante di una cifra)
- **Amundi MSCI EU** (ISIN `LU1949199711` — non trovato; il piu' simile e' `LU1940199711`,
  Amundi MSCI Europe ESG Selection)

Verifica l'ISIN esatto sul tuo estratto conto titoli Intesa, cercalo su
[justetf.com](https://www.justetf.com) o [borsaitaliana.it](https://www.borsaitaliana.it) per
trovare il ticker Yahoo Finance corretto (es. `XXXX.MI` o `XXXX.PA`), poi aggiorna la voce:

```json
{ "name": "Amundi MSCI Asia", "ticker": "TICKER_CORRETTO", "isin": "ISIN_CORRETTO", "enabled": true }
```

### 6. Primo run

Tab **Actions → Stock monitor → Run workflow**. Apri il log per verificare che non ci siano
errori, poi controlla che `docs/state.json` sia stato aggiornato e che la dashboard mostri i dati.

Da qui in poi gira da solo ogni 15 minuti nei giorni di borsa (lun-ven, 7:00-21:00 UTC).

## Gestire la watchlist

Modifica `watchlist.json` direttamente da GitHub (anche da smartphone, app GitHub → apri file →
matita per modificare → commit). Ogni voce:

```json
{ "name": "Nome leggibile", "ticker": "TICKER.MI", "threshold_pct": 2.0, "enabled": true }
```

- `threshold_pct` e' opzionale: se omesso usa `default_threshold_pct` (2%) definito in cima al file.
- Per rimuovere un titolo dal monitoraggio senza cancellarlo: `"enabled": false`.

## Cambiare l'algoritmo di trend

`trend_algorithm.py` contiene l'unico punto da modificare. Al momento implementa una derivata
filtrata semplice:

1. media mobile esponenziale sul prezzo di chiusura (riduce il rumore)
2. variazione percentuale giorno su giorno della serie smussata (la "derivata")
3. smussatura anche della derivata, per stabilita'
4. se supera `rise_threshold_pct_per_day` → segnale "up"; se scende sotto
   `fall_threshold_pct_per_day` (negativo) → segnale "down"

Le soglie e la finestra di smoothing sono in `config.json` → `trend_algorithm`. Storico e
intervallo usati (`3mo`, giornaliero) sono in `config.json` → `market_data`.

Per sostituire l'algoritmo: riscrivi il corpo della funzione `detect_trend(history, params)` in
`trend_algorithm.py`, mantenendo la stessa firma — riceve un DataFrame pandas con colonna
`Close` e il dict `params` da `config.json`, deve restituire
`{"signal": "up"|"down"|"none", "value": <numero>}`. `monitor.py` non richiede nessuna modifica.

## Anti-spam degli alert

- **Soglia assoluta**: al primo superamento della soglia manda l'alert e sposta il riferimento
  (baseline) al prezzo corrente — il prossimo alert scatta solo dopo un altro movimento pari alla
  soglia da li'. La baseline si resetta a inizio di ogni giornata di borsa.
- **Trend**: manda un alert solo quando il segnale *cambia* (es. da "none" a "up"), non ad ogni
  esecuzione mentre il trend persiste.

## File

```
watchlist.json              titoli monitorati, soglie
config.json                 parametri storico e algoritmo trend
trend_algorithm.py          algoritmo di trend detection (sostituibile)
monitor.py                  script principale, gira via GitHub Actions
docs/index.html             dashboard mobile (GitHub Pages)
docs/state.json             stato aggiornato ad ogni run (letto dalla dashboard)
.github/workflows/monitor.yml   cron GitHub Actions
```
