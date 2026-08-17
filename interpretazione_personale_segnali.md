# Interpretazione personale dei segnali (bozza, non parte del sistema)

> Nota: questo testo contiene letture predittive/probabilistiche (es. "accumulazione
> istituzionale", "probabilità statistica che il prezzo reagisca aumenta drasticamente",
> "movimento macro-direzionale violentissimo") che il codice del sistema NON calcola e
> non supporta. È conservato qui come appunto personale su richiesta esplicita, non come
> documentazione tecnica — quella resta nel Manuale dei Segnali (artifact) e nel README,
> dove ogni claim è verificabile nel codice.

Questo sistema di monitoraggio è strutturato come un algoritmo di validazione a cascata. Non fa previsioni sul futuro, ma risponde a una logica rigorosa: identifica un'anomalia statistica (Soglia), ne verifica la forza strutturale (Trend) e mappa i confini geometrici in cui si trova (Livello).

Ecco il significato operativo e dinamico di ciascun output in termini di potenziale comportamento del prezzo.

## 🚨 Output 1: [SOGLIA] (Variazione Infragiornaliera)

Questo alert indica un impulso direzionale immediato. Misurando solo il prezzo rispetto all'apertura, rileva la pressione dei compratori o dei venditori nella singola sessione di borsa.

**Significato dell'andamento**: Indica la presenza di volatilità oraria o notizie macro/societarie uscite a mercati aperti. Se il prezzo si muove del +2% o -2% in poche ore, significa che gli operatori stanno prendendo posizione con forza oggi.

**Logica del meccanismo "a cricchetto"**: Serve a capire se il movimento è continuo o se si sta esaurendo. Se ricevi un alert a -2%, e dopo un'ora ne ricevi un altro a -4%, il titolo è in caduta libera (free fall). Se l'alert si ferma, il prezzo sta consolidando sui minimi o massimi di giornata.

## 📈 Output 2: [TREND] (MACD + ADX)

Questo output definisce lo stato di salute e l'inerzia del titolo su un orizzonte di medio termine (3 mesi). La combinazione dei due indicatori pulisce il grafico dai "falsi segnali".

- **up con ADX > 25**: Il titolo ha una forte inerzia rialzista. In termini di andamento, significa che la tendenza è solida e ogni calo temporaneo viene probabilmente comprato. C'è accumulazione istituzionale.
- **down con ADX > 25**: Il titolo ha una forte inerzia ribassista. La pressione in vendita è costante e strutturale. Il titolo sta "perdendo pezzi" nel medio periodo.
- **none (ADX < 25)**: Il titolo è in una fase laterale (trading range). Il prezzo oscilla senza direzione. In questo scenario, i segnali del MACD vanno ignorati perché il mercato sta "riposando" o accumulando energia per il prossimo movimento.

## 🛡️ Output 3: [LIVELLO] (Geometria del Prezzo e Volatilità)

Questo è il check più complesso perché unisce la memoria storica del prezzo (Pivot), le proporzioni matematiche (Fibonacci) e la compressione/espansione della volatilità (Bollinger).

I 5 segnali possibili descrivono scenari dinamici precisi:

### 1. near_support (Vicino al Supporto)

**Significato**: Il prezzo è sceso fino al "pavimento" storico o a un livello Fibonacci chiave.

**Potenziale andamento**: Fase di test. Se il supporto tiene, il titolo potrebbe rimbalzare verso l'alto. Se il supporto fallisce, il titolo accelererà al ribasso. L'isteresi (1.0% - 1.5%) evita i falsi allarmi se il prezzo "calpesta" il pavimento senza romperlo.

### 2. near_resistance (Vicino alla Resistenza)

**Significato**: Il prezzo è salito fino al suo "soffitto" storico o a un livello Fibonacci.

**Potenziale andamento**: Il rally a breve termine potrebbe esaurirsi. Qui i venditori di solito prendono il sopravvento. È l'esatta situazione descritta nel messaggio d'esempio del sistema su EGOV.MI (prezzo a 49.16, resistenza a 49.29). Il titolo sta esaurendo la spinta proprio sotto un livello importante (confluenza Pivot + Fib).

### 3. breakout_resistance (Rottura della Resistenza)

**Significato**: Il prezzo ha superato il soffitto. Se accompagnato dall'uscita dalle bande di Bollinger, c'è un'espansione di volatilità.

**Potenziale andamento**: Forte accelerazione rialzista. La rottura di una resistenza storica (con più tocchi) combinata con Bollinger indica che i compratori hanno rotto gli argini. Il vecchio soffitto diventa ora il nuovo pavimento (supporto).

### 4. breakdown_support (Rottura del Supporto)

**Significato**: Il prezzo ha bucato il pavimento verso il basso.

**Potenziale andamento**: Accelerazione ribassista (panico). Chi aveva comprato sul supporto ora è in perdita e vende per limitare i danni (stop loss), alimentando il crollo. È un segnale di grave deterioramento tecnico.

### 5. none

**Significato**: Il prezzo naviga nella "terra di nessuno", a metà strada tra i livelli chiave. L'andamento è regolare e non ci sono ostacoli geometrici immediati.

## 📊 Il "Conteggio dei Segnali Concordanti": La Confluenza

La vera potenza del sistema risiede nell'ultimo blocco. Quando più check indipendenti puntano nella stessa direzione, la probabilità statistica che il prezzo reagisca aumenta drasticamente.

| Numero Segnali | Significato in termini di andamento |
|---|---|
| 0 o 1 segnale | Rumore di fondo. Il mercato sta testando i livelli in modo isolato. La situazione è ambigua. |
| 2 segnali | Interesse in aumento. Ad esempio: Rottura Livello + Confluenza Fibonacci. Significa che il livello grafico rotto era matematicamente molto importante. |
| 3 o 4 segnali | Anomalia ad alta intensità. Ad esempio: breakout_resistance + Trend up (ADX alto) + Bollinger Espansione + Confluenza Fib. Significa che il titolo sta avviando un movimento macro-direzionale violentissimo. Tutti i partecipanti al mercato (trader di breve, investitori di medio, algoritmi di volatilità) stanno spingendo dalla stessa parte. |
