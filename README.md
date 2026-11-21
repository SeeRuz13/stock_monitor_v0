# Stock Monitor – PAC e compravendite rapide

Ti aiuta a decidere **quando e quanto comprare**, con due strategie separate:

1. **PAC modulato** (medio periodo, 3-5 anni): ogni mese ti dice quanto investire e su quali
   ETF. Compra di più quando il mercato è sceso, meno quando è "caro".
2. **Compravendite rapide** (2-15 giorni, solo acquisti): ogni sera cerca dei setup su ~80
   titoli liquidi (Italia, Europa, USA) e ti manda un piano completo: entrata, stop, obiettivo,
   quantità.

Ogni regola è **verificata sullo storico di 10 anni** (backtest settimanale): un setup che su un
titolo ha perso soldi in passato non ti viene proposto su quel titolo. Le operazioni proposte
vengono poi seguite **su carta** in automatico, così vedi se funzionano anche dal vivo prima
di metterci soldi veri.

Tutto gira su GitHub Actions (nessun PC acceso), con messaggi Telegram e una dashboard su
GitHub Pages.

> Strumento di supporto alle decisioni, non consulenza finanziaria. Il passato non garantisce
> il futuro.

---

## 1. PAC modulato

**Cosa fa**: il primo giorno di borsa di ogni mese ricevi un messaggio tipo:

```
📅 PAC dicembre 2026
Mercato (MSCI World): -7,2% dai massimi a 1 anno → ×1,25
Questo mese investi 3.750 €:
• 2.340 € su Amundi MSCI World (ISIN LU1681043599)
• 1.410 € su Amundi Euro Government Bond (ISIN LU1437018598)
Investito finora: 6.000 € su 40.000 € (15%)
Quando hai comprato rispondi «pac fatto» (oppure «pac saltato»).
```

**Moltiplicatore** (in base all'MSCI World):

| Situazione del mercato | Importo |
|---|---|
| normale (meno del 5% sotto i massimi a 1 anno) | 1× |
| 5-10% sotto i massimi | 1,25× |
| 10-20% sotto i massimi | 1,5× |
| oltre 20% sotto i massimi | 2× |
| più del 15% sopra la media a 200 giorni ("caro") | 0,75× |

**Portafoglio obiettivo** (adatto a un orizzonte di 3-5 anni):

| ETF | ISIN | Peso |
|---|---|---|
| Amundi MSCI World | LU1681043599 | 50% |
| Amundi MSCI Emerging Markets | LU1681045370 | 10% |
| Amundi Euro Government Bond | LU1437018598 | 30% |
| Gold Bullion Securities | GB00B00FHZ82 | 10% |

Ogni mese si comprano **solo 1-2 ETF**, quelli più sotto il loro peso obiettivo. Così il
portafoglio si ribilancia da solo senza mai vendere, e si usano poche operazioni (vincolo
delle 10 operazioni gratuite al mese su Revolut).

**Comandi Telegram** (solo dal tuo account):
- `pac fatto`: hai comprato quanto suggerito, il sistema lo registra
- `pac saltato`: questo mese non hai comprato
- `stato`: riepilogo del PAC (investito, valore attuale, pesi)

I comandi vengono letti ogni 4 ore, tutti i giorni (workflow "Comandi Telegram"),
quindi la risposta può arrivare dopo qualche ora. Conferma l'acquisto entro fine
mese: al primo run del mese successivo un suggerimento non confermato scade.

Importi e posizioni del PAC sono **privati**: stanno in `private_state.json` (cifrato) e
nei messaggi Telegram, mai nella dashboard pubblica.

## 2. Compravendite rapide

**Solo acquisti**, solo su titoli sopra la media a 200 giorni (tendenza di fondo positiva).
Due setup:

- **Ritracciamento nel trend**: titolo in salita che ha avuto 2-3 giorni di calo (RSI a 2
  giorni sotto 10). Si compra il rimbalzo e si esce alla prima chiusura sopra la media a 5
  giorni. Stop a 2,5 ATR, massimo 10 sedute.
- **Rottura dei massimi**: chiusura sopra il massimo delle ultime 20 sedute con volumi 1,5
  volte sopra la media. Stop a 2 ATR, obiettivo a 4 ATR (rapporto 2:1), massimo 15 sedute.

(L'ATR è l'escursione media giornaliera del titolo: stop e obiettivi si adattano alla
volatilità di ciascuno.)

**Messaggio tipo**:

```
🟢 Intesa Sanpaolo (ISP.MI) – ritracciamento nel trend
Compra all'apertura di domani (~4,12 €)
Stop: 3,95 € (-4,1%) – inseriscilo subito come ordine stop
Uscita: alla prima chiusura sopra la media a 5 giorni (oggi ~4,25 €), o dopo 10 sedute
Quantità: 600 → 2.472 €, rischio max 100 €
Storico su questo titolo: 41 operazioni, 63% vincenti, media +0,62% a operazione
```

**Gestione del rischio**:
- ogni operazione rischia al massimo l'**1% del capitale** di trading (quantità calcolata in
  automatico), e nessuna posizione supera 1/3 del capitale;
- massimo **3 posizioni aperte** e **3 nuove operazioni al mese** (ogni compravendita usa
  2 delle 10 operazioni gratuite; con 2 acquisti PAC si arriva a 8 su 10);
- costi stimati nel backtest: 0,1% per lato più 0,1% sui titoli non in euro (cambio).

**Simulazione su carta**: ogni proposta viene seguita in automatico in `docs/swing_log.json`
(entrata all'apertura del giorno dopo, stop/obiettivo/tempo come da piano). Ricevi un
messaggio quando un'operazione si chiude e un riepilogo ogni venerdì. Consiglio: **2-3 mesi
solo su carta** prima di usare soldi veri.

**Universo**: `universe.json`, circa 80 titoli molto scambiati (FTSE MIB, grandi europee,
grandi USA). Puoi aggiungere o togliere titoli liberamente; controlla che siano acquistabili
sul tuo broker.

## Backtest

`backtest.py` gira ogni domenica (e a mano da **Actions → Backtest → Run workflow**):

- per ogni titolo e setup: numero di operazioni, % vincenti, guadagno e perdita medi,
  risultato medio a operazione, profit factor, durata media. Anche per mercato e per anno;
- per il PAC: su tutte le finestre di 4 anni dello storico dell'MSCI World, confronto tra
  "tutto subito", PAC semplice e PAC modulato.

I risultati finiscono in `docs/backtest.json` e nella dashboard.

**Limiti onesti**: l'universo contiene le aziende grandi *oggi* (quelle fallite o uscite dagli
indici non ci sono, e questo migliora un po' i risultati passati); le tasse (26%) non sono
incluse; ingresso e uscita sono simulati su prezzi giornalieri.

---

## Setup

### Secrets (Settings → Secrets and variables → Actions → Secrets)

- `TELEGRAM_BOT_TOKEN`: token del bot (da @BotFather)
- `TELEGRAM_CHAT_ID`: il tuo chat_id. I messaggi vanno solo al primo della lista, perché
  contengono importi personali.
- `PORTFOLIO_ENCRYPTION_KEY`: chiave di cifratura dello stato privato. Per generarla:
  ```
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

### Variables (stessa pagina, scheda **Variables**: non sono visibili pubblicamente)

| Nome | Significato | Default |
|---|---|---|
| `PAC_BUDGET` | totale da investire col PAC | 40000 |
| `PAC_MONTHLY_BASE` | importo base mensile | 3000 |
| `SWING_CAPITAL` | capitale per le compravendite rapide | 10000 |

Gli importi non stanno in `config.json` perché il repo è pubblico.

### Primo avvio

1. **Actions → Backtest → Run workflow** (qualche minuto): senza backtest non arrivano proposte.
2. **Actions → Daily run → Run workflow**: arriva il primo messaggio PAC e gli eventuali setup.
3. Da lì in poi gira da solo: ogni sera lun-ven alle 21:30 UTC, backtest ogni domenica.

Dashboard: **Settings → Pages** → branch `main`, cartella `/docs`.

### Test offline

```
python tests/test_core.py
```

## Parametri

Tutto in `config.json`: pesi degli ETF, moltiplicatori, rischio per operazione, numero
massimo di posizioni, soglie dei setup. Se cambi una soglia dei setup, rilancia il backtest.

## File

```
config.json          parametri (PAC, setup, rischio)
universe.json        titoli scansionati per le compravendite rapide
daily_run.py         run serale: comandi Telegram, PAC, setup, simulazione
backtest.py          backtest settimanale (setup + PAC)
swing_strategy.py    setup, piano di trade, simulazione, dimensionamento
pac.py               moltiplicatore, ripartizione tra ETF, backtest PAC
indicators.py        SMA, RSI, ATR, drawdown
common.py            Telegram, cifratura, download dati (Yahoo Finance)
private_state.json   stato PAC cifrato (creato al primo run)
docs/index.html      dashboard
docs/state.json      stato pubblico (senza importi)
docs/swing_log.json  operazioni simulate
docs/backtest.json   risultati del backtest
tests/test_core.py   test offline
```
