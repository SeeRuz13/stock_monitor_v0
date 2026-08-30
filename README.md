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
- `TELEGRAM_CHAT_ID` — il chat_id recuperato sopra. Per mandare gli alert anche ad altre
  persone (stessa watchlist per tutti), metti più chat_id separati da virgola, es.
  `8010961959,123456789` — vedi "Condividere con altri" più sotto.

### 4. Abilita GitHub Pages

**Settings → Pages** → Source: "Deploy from a branch" → Branch: `main`, cartella `/docs` → Save.
Dopo qualche minuto la dashboard sara' visibile su `https://TUO_USER.github.io/stock-monitor/`.
Salvatela come collegamento nella home del telefono per accedervi come un'app.

### 5. Primo run

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
- Per aggiungere un nuovo titolo partendo dall'ISIN: cercalo su
  [justetf.com](https://www.justetf.com) o [borsaitaliana.it](https://www.borsaitaliana.it) per
  trovare il ticker Yahoo Finance corretto (es. `XXXX.MI` per Milano, `XXXX.PA` per Parigi).

## Cambiare l'algoritmo di trend

`trend_algorithm.py` contiene l'unico punto da modificare. Al momento implementa **MACD
filtrato da ADX**, due indicatori tecnici standard:

1. **MACD** (Moving Average Convergence Divergence): `EMA12 - EMA26` = linea MACD,
   `EMA9(MACD)` = signal. MACD sopra signal → direzione rialzista, sotto → ribassista.
2. **ADX** (Average Directional Index, Wilder, 14 periodi): misura la forza del trend
   (0-100), indipendente dalla direzione. Se ADX è sotto `adx_threshold` (default 25) il
   mercato è considerato laterale/rumoroso e il segnale MACD viene scartato (`"none"`),
   anche se ha appena incrociato — questo riduce i falsi positivi rispetto a un semplice
   incrocio di medie.

I parametri (`macd_fast`, `macd_slow`, `macd_signal`, `adx_period`, `adx_threshold`) sono in
`config.json` → `trend_algorithm`. Storico e intervallo usati (`3mo`, giornaliero) sono in
`config.json` → `market_data`.

Per sostituire l'algoritmo: riscrivi il corpo della funzione `detect_trend(history, params)` in
`trend_algorithm.py`, mantenendo la stessa firma — riceve un DataFrame pandas con colonne
`High`, `Low`, `Close` e il dict `params` da `config.json`, deve restituire
`{"signal": "up"|"down"|"none", "value": <numero>}` (più eventuali chiavi extra, es. `"adx"`,
usate solo per arricchire il messaggio di alert in `monitor.py`).

## Cambiare l'algoritmo di supporti/resistenze, Fibonacci e Bollinger

`levels_algorithm.py` implementa il terzo check, che genera alert `[LIVELLO]`. Combina tre
tecniche; le prime due condividono la stessa base — la ricerca dei **pivot** (massimi/minimi
locali confermati) sul prezzo storico:

1. **Supporti/resistenze**: i pivot vicini tra loro vengono raggruppati in "zone"; una zona
   toccata almeno `min_touches` volte diventa un supporto (se sotto il prezzo attuale) o una
   resistenza (se sopra) — il ruolo si aggiorna da solo ad ogni run confrontando col prezzo
   attuale, quindi un'inversione supporto↔resistenza avviene automaticamente.
2. **Fibonacci**: sull'ultimo swing significativo (massimo/minimo pivot più recenti entro
   `fib_lookback_bars`, non barre grezze) calcola i 5 livelli di ritracciamento standard
   (23.6/38.2/50/61.8/78.6%).
3. **Bollinger Bands** (`bollinger_window` giorni, `bollinger_std` deviazioni standard): non
   generano un segnale a parte, confermano (o no) una rottura già rilevata dai pivot/Fibonacci.
   Se una rottura (`breakout_resistance`/`breakdown_support`) coincide con un'uscita dalla banda
   corrispondente, `volatility_confirmation` diventa `true` — indica che il movimento ha
   un'espansione di volatilità dietro, non solo un lento superamento della soglia.

Quando un supporto/resistenza e un livello Fibonacci coincidono (entro `cluster_tolerance_pct`),
scatta la **confluenza** — due tecniche indipendenti che indicano lo stesso prezzo, un segnale
più solido di uno preso da una sola delle due — e compare nel messaggio dell'alert insieme
all'eventuale conferma di volatilità.

Il segnale scatta per "vicinanza" a un livello (`near_support`/`near_resistance`, entro
`proximity_pct`) o per rottura (`breakout_resistance`/`breakdown_support`, chiusura precedente
da un lato del livello e prezzo attuale dall'altro). La "vicinanza" usa un'isteresi
(`hysteresis_factor`) per non generare alert ad ogni run se il prezzo oscilla al margine della
soglia.

Parametri in `config.json` → `levels_algorithm` (`pivot_window`, `cluster_tolerance_pct`,
`min_touches`, `max_zones`, `proximity_pct`, `hysteresis_factor`, `fib_lookback_bars`,
`bollinger_window`, `bollinger_std`). Usa uno storico più lungo
(`market_data.levels_history_period`, default 6 mesi) rispetto al trend (3 mesi): supporti/
resistenze/Fibonacci hanno bisogno di più storia per essere significativi.

Il messaggio `[LIVELLO]` include anche un riepilogo di **quanti segnali indipendenti concordano**
in questo momento (trend, rottura confermata, espansione di volatilità, confluenza Fibonacci) —
è un conteggio di fatti verificabili sullo stato attuale, non una previsione su come andrà il
titolo (vedi `signal_agreement()` in `monitor.py`).

Per sostituire l'algoritmo: `detect_levels(history, params, current_price, previous_signal)` in
`levels_algorithm.py` — firma diversa da `detect_trend` perché qui servono anche il prezzo live
e il segnale precedente (per l'isteresi). Deve restituire almeno
`{"signal": "none"|"near_support"|"near_resistance"|"breakout_resistance"|"breakdown_support", "value": <numero>}`,
più le chiavi extra usate da `monitor.py`/dashboard (`level_price`, `level_label`,
`nearest_support`, `nearest_resistance`, `fib_levels`, `fib_direction`).

## Report giornaliero PDF (validazione delle formule nel tempo)

`daily_report.py` gira **una volta al giorno** (cron separato, `.github/workflows/daily_report.yml`,
21:15 UTC nei giorni di borsa — un quarto d'ora dopo l'ultimo run regolare) e fa due cose:

1. Aggiunge una riga a `docs/daily_log.json` per ogni titolo: data, prezzo di chiusura, badge
   trend/livello, segnali concordanti di quel giorno. È un file che **cresce nel tempo** (mai
   sovrascritto, un giorno alla volta) — pensato per poter verificare col tempo se i badge del
   sistema hanno anticipato davvero i movimenti successivi, non solo per consultazione immediata.
2. Genera un PDF con la tabella (titolo, prezzo, delta oggi, S/R, badge, segnali concordanti, più
   una colonna per ciascuno degli ultimi `max_days_shown` giorni accumulati) e lo manda come
   allegato via Telegram (stesso bot degli alert, `sendDocument`).

Il PDF mostra solo gli ultimi `max_days_shown` giorni (default 10) per restare leggibile — lo
storico completo resta comunque tutto in `docs/daily_log.json`, anche quando cresce oltre quella
finestra.

**Per fermarlo**: `config.json` → `daily_report` → `"enabled": false` (lo script esce subito senza
fare nulla), oppure disabilita il workflow da GitHub: **Actions → Daily report → ⋯ → Disable
workflow**.

Parametri in `config.json` → `daily_report` (`enabled`, `max_days_shown`).

## Portafoglio via comandi Telegram

Puoi scrivere al bot per segnare quali titoli possiedi davvero in questo momento (non serve
modificare `watchlist.json` a mano). Il comando viene letto entro 15 minuti (al prossimo run
regolare di `monitor.py` — nessun server sempre acceso, quindi non è istantaneo).

**Comandi**: nome titolo, ticker o ISIN + una parola tra `comprato`/`acquistato`/`compro`/
`acquisto` (per aggiungere) o `venduto`/`vendo`/`vendita` (per rimuovere), in qualsiasi ordine —
es. `comprato Ferrari` o `Ferrari comprato` funzionano uguale. Il bot risponde con una conferma,
o ti chiede di essere più specifico se il nome è ambiguo (es. "Amundi MSCI" da solo corrisponde a
4 fondi diversi — serve il nome completo o il ticker).

**Solo tu puoi dare questi comandi**: il bot accetta comandi solo dalla chat che hai usato per il
primo setup (`TELEGRAM_CHAT_ID`, il primo valore se ne hai messi più di uno per condividere gli
alert con altri) — un amico che scrive "comprato X" viene ignorato silenziosamente, il tuo
portafoglio resta un fatto privato tra te e il bot.

**Titoli "in portafoglio" sono trattati diversamente**:
- soglia di alert più stretta di quella generale (`config.json` → `portfolio` →
  `held_threshold_pct`, default 1.0% invece del 2% generale) — override per singolo titolo con
  `held_threshold_pct` nella voce di `watchlist.json`, stesso meccanismo di `threshold_pct`
- marcati con `[PORTAFOGLIO]` nei messaggi `[SOGLIA]`/`[TREND]`/`[LIVELLO]` e nel PDF giornaliero

**Privacy**: `portfolio.json` (quali titoli possiedi davvero) è **cifrato** prima di essere
committato — a differenza di prezzi/segnali tecnici (già pubblici in `docs/state.json` per la
dashboard), la tua posizione reale è un'informazione più sensibile, e il repo resta pubblico
(necessario per GitHub Pages gratuito). Cifratura simmetrica (libreria `cryptography`, Fernet),
chiave nel secret `PORTFOLIO_ENCRYPTION_KEY` — senza quel secret nessuno può leggere il contenuto
del file, nemmeno aprendolo direttamente su github.com. Per generarne una nuova (es. se sospetti
che la chiave sia stata esposta):
```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
poi aggiorna il secret su GitHub — attenzione, un file già cifrato con la vecchia chiave non sarà
più leggibile con una chiave nuova (verrebbe ricreato vuoto al primo run).

**Per disattivare**: `config.json` → `portfolio` → `"enabled": false`.

## Condividere con altri

Gli alert vengono mandati a ogni chat_id presente nel secret `TELEGRAM_CHAT_ID` (separati da
virgola) — stessa watchlist e soglie per tutti, non c'e' personalizzazione per persona. Per
aggiungere qualcuno:

1. L'amico cerca il bot su Telegram (username scelto al punto 2 del setup) e gli manda un
   messaggio qualsiasi (es. "ciao") — senza questo passaggio Telegram non permette al bot di
   scrivergli.
2. Recupera il suo chat_id aprendo nel browser
   `https://api.telegram.org/bot<TOKEN>/getUpdates` e cercando il suo `"chat":{"id": ...}`
   nella risposta (compare dopo che ti ha scritto).
3. Aggiorna il secret `TELEGRAM_CHAT_ID` su GitHub con la lista completa separata da virgola.

Nessuna modifica al codice necessaria oltre a questo.

## Anti-spam degli alert

- **Soglia assoluta**: al primo superamento della soglia manda l'alert e sposta il riferimento
  (baseline) al prezzo corrente — il prossimo alert scatta solo dopo un altro movimento pari alla
  soglia da li'. La baseline si resetta a inizio di ogni giornata di borsa.
- **Trend**: manda un alert solo quando il segnale *cambia* (es. da "none" a "up"), non ad ogni
  esecuzione mentre il trend persiste.
- **Livelli**: come il trend (alert solo al cambio di segnale), con in più un'isteresi sulla
  soglia di "vicinanza" a un livello, per non generare alert ad ogni run se il prezzo oscilla
  al margine della soglia (vedi sopra).

## File

```
watchlist.json              titoli monitorati, soglie
config.json                 parametri storico e algoritmi (trend, livelli, report, portafoglio)
trend_algorithm.py          algoritmo di trend detection (sostituibile)
levels_algorithm.py         algoritmo supporti/resistenze + Fibonacci (sostituibile)
portfolio.py                comandi Telegram comprato/venduto + cifratura portfolio.json
portfolio.json               titoli posseduti, cifrato (mai leggibile senza il secret)
monitor.py                  script principale, gira via GitHub Actions ogni 15 min
daily_report.py             accumulo storico + PDF giornaliero via Telegram
docs/index.html             dashboard mobile (GitHub Pages)
docs/state.json             stato aggiornato ad ogni run (letto dalla dashboard)
docs/daily_log.json         storico giornaliero cumulativo (letto da daily_report.py)
.github/workflows/monitor.yml        cron GitHub Actions ogni 15 min
.github/workflows/daily_report.yml   cron GitHub Actions una volta al giorno
```
