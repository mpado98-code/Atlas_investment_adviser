# Atlas - Bot Telegram di consulenza investimenti personale (Gemini edition)

Bot Telegram che fa da consulente AI per i tuoi investimenti su Directa.
Lo usi dal Google Pixel 9 (o qualsiasi telefono) come una normale chat:
gli mandi screenshot del portafoglio, lui legge, analizza, suggerisce.

**Cervello**: Google Gemini 2.5 Pro (gratis sul tier free di Google AI Studio)
con visione + Google Search grounding per dati live.
**Filosofia**: condensa il pensiero di Dalio, Buffett, Marks, Klarman, Munger,
Grantham, Druckenmiller, Lynch.

> **Costo totale per uso personale: 0 EUR / mese** (hosting free + API free).

---

## Cosa fa il bot

- Legge screenshot del portafoglio Directa ed estrae le posizioni
- Analizza allocazione per asset class, geografia, settore, valuta, fattori
- Identifica concentrazioni, sovrapposizioni, costi inefficienti
- Suggerisce miglioramenti motivati (mai segnali di trading a brevissimo)
- Discute singoli titoli, scenari macro, geopolitica
- Segnala opportunita' solo dove vede asimmetria favorevole

---

## Setup (~30 minuti, una volta sola)

### Passo 1 - Crea il bot su Telegram

1. Apri Telegram (anche dal Pixel) e cerca `@BotFather`
2. Manda `/newbot`
3. Scegli un nome (es. "Atlas Investment Coach")
4. Scegli uno username che finisca con `bot` (es. `marco_atlas_bot`)
5. BotFather ti dara' un **token** del tipo `123456789:ABCdef...` - **salvalo**

### Passo 2 - Ottieni il tuo Telegram user_id

1. Su Telegram cerca `@userinfobot`
2. Avvialo con `/start`
3. Ti restituisce il tuo `Id` numerico (es. `987654321`) - **salvalo**

### Passo 3 - Crea l'API key Google (gratuita)

1. Vai su https://aistudio.google.com/apikey (anche dal Pixel)
2. Accedi con il tuo account Google
3. Clicca **Create API key** -> seleziona un progetto (o creane uno nuovo)
4. Copia la chiave del tipo `AIzaSy...` - **salvala**

**Limiti del tier gratuito** (al momento della scrittura):
- Gemini 2.5 Pro: ~100 richieste/giorno, ~5 al minuto
- Gemini 2.5 Flash: ~250 richieste/giorno, ~10 al minuto
- Entrambi includono visione e Google Search grounding

Per uso personale (10-30 query/giorno) il free tier basta e avanza. Se ti
avvicini al limite, cambia `GEMINI_MODEL` da `gemini-2.5-pro` a
`gemini-2.5-flash` (piu' veloce, limiti piu' alti, qualita' leggermente
inferiore ma comunque ottima).

### Passo 4 - Deploy su Railway (gratis, sempre online)

Railway ha un tier gratuito che basta e avanza per un bot personale.

1. Vai su https://railway.app e iscriviti (login con GitHub)
2. Crea un repo GitHub privato con dentro tutti i file di questa cartella
   `investment-agent/` (`bot.py`, `prompts.py`, `requirements.txt`,
   `Procfile`, `runtime.txt`, `railway.json`)
3. Su Railway: **New Project** -> **Deploy from GitHub repo** -> seleziona il repo
4. Una volta partito il build, vai su **Variables** e aggiungi:
   - `TELEGRAM_BOT_TOKEN` = il token del passo 1
   - `GOOGLE_API_KEY` = la chiave del passo 3
   - `TELEGRAM_ALLOWED_USER_IDS` = il tuo user_id del passo 2
5. Railway fa redeploy automatico. Nei log devi vedere
   `Atlas avviato. Modello=gemini-2.5-pro, web_search=True`

### Passo 5 - Prova il bot

1. Sul Pixel apri Telegram, cerca il bot che hai creato (es. `@marco_atlas_bot`)
2. Manda `/start`
3. Manda uno screenshot del tuo portafoglio Directa
4. Goditi l'analisi

**Suggerimento Pixel 9**: aggiungi la chat del bot alla home come scorciatoia
(menu a tre puntini in alto a destra in Telegram -> "Aggiungi a schermata
home"). Cosi' la lanci come fosse un'app dedicata.

---

## Alternativa: deploy su Render

Render funziona analogamente a Railway, tier gratuito disponibile:

1. https://render.com -> **New** -> **Background Worker**
2. Connetti il repo GitHub
3. Build command: `pip install -r requirements.txt`
4. Start command: `python bot.py`
5. Aggiungi le stesse variabili d'ambiente del passo 4

---

## Alternativa: girare localmente sul PC

```bash
cd investment-agent
python -m venv .venv
source .venv/bin/activate     # o .venv\Scripts\activate su Windows
pip install -r requirements.txt
cp .env.example .env
# edita .env con i tuoi valori
set -a; source .env; set +a   # carica le var (linux/mac)
python bot.py
```

Funziona solo finche' il PC e' acceso e il processo in esecuzione.

---

## Come si usa quotidianamente

**Analisi iniziale**:
1. Su Directa: schermata "Portafoglio" -> screenshot (Pixel: Power + Volume Giu')
2. Inviala al bot via Telegram
3. Se il portafoglio non sta in una schermata, manda piu' screenshot uno dopo
   l'altro
4. Aggiungi una nota libera, es: "orizzonte 10 anni, profilo aggressivo,
   3000 EUR mensili di PAC"

**Domande tipiche**:
- "Sono troppo esposto al tech US?"
- "Che ne pensi di sostituire questo fondo con un ETF MSCI World?"
- "Con i tassi BCE in calo, ha senso aumentare la duration sui bond?"
- "Stiamo entrando in fase di euforia? Quanto cash dovrei tenere?"
- "ENI vs Shell vs Exxon - quale ha il miglior profilo rischio/rendimento?"

**Comandi**:
- `/start` - messaggio di benvenuto
- `/portfolio` - riepiloga il portafoglio che il bot ha memorizzato
- `/reset` - cancella la memoria della conversazione (usalo se vuoi ripartire da zero)
- `/help` - aiuto

---

## Costi

| Voce | Costo |
|------|-------|
| Bot Telegram | 0 EUR |
| Railway/Render free tier | 0 EUR (entro i limiti del tier) |
| Google Gemini API (free tier) | 0 EUR fino ai limiti di quota giornalieri |

Se superi spesso le 100 query/giorno con Gemini 2.5 Pro: o passi a Flash
(stesso tier gratuito, limiti piu' alti) o attivi il billing su Google AI
Studio. Costi paid tier (al momento della scrittura): Gemini 2.5 Pro ~1.25 USD
per 1M token input, ~10 USD per 1M token output. Per uso personale anche
intensivo si parla di pochi euro al mese.

---

## Sicurezza e privacy

- La variabile `TELEGRAM_ALLOWED_USER_IDS` fa da whitelist: solo tu puoi
  parlarci. Se qualcun altro trova il bot, riceve "Accesso non autorizzato".
- Le conversazioni vengono salvate in `./conversations/<user_id>.json` sul
  server dove gira il bot. Su Railway free tier sono effimere (si perdono ad
  ogni redeploy): se ti serve persistenza vera, aggiungi un Postgres free tier
  o un volume Railway.
- **Importante per il free tier Google**: per i modelli usati nel tier gratuito
  Google puo' usare il contenuto delle conversazioni per migliorare i propri
  prodotti (vedi https://ai.google.dev/gemini-api/terms). Se per te questo e'
  un problema, attiva un account paid (Gemini API paid tier) - in quel caso
  Google NON usa i dati per training.
- Non condividere mai il token del bot ne' l'API key. Se ti accorgi che sono
  leakati, revocali subito (BotFather: `/revoke`; Google AI Studio: cancella e
  rigenera la chiave).

---

## Estensioni future (chiedimi quando vuoi)

- Briefing mattutino automatico (cronjob + Telegram)
- Alert su movimenti macro o sui tuoi titoli
- Integrazione vera con Directa via API socket (richiede PC sempre acceso col
  Trading Studio aperto - alta complessita')
- Import periodico CSV export di Directa per dati piu' strutturati
- Dashboard web con grafici dell'allocazione
- Switch dinamico tra Gemini Pro/Flash in base al carico

---

## Limiti e disclaimer

Atlas e' uno **strumento educativo**, non sostituisce un consulente finanziario
abilitato. Le sue analisi sono opinioni generate da un LLM basate su
informazioni pubbliche e sui dati che gli fornisci. **Tutte le decisioni di
investimento restano tue.** Investire comporta rischi di perdita del capitale.
