# 🚆 Bot Monitor Trenitalia Pro (Multi-Tratta & Inviti Monouso)

Bot avanzato in Python per il monitoraggio della disponibilità dei posti, delle aperture vendite e delle variazioni di prezzo dei treni **Trenitalia** su qualsiasi tratta nazionale.

Completamente gestibile tramite **Telegram con pulsanti interattivi touch**, sistema di **link di invito monouso ad accesso singolo** per gli amici, e pronto per l'hosting continuo **24 ore su 24 gratuito su Render.com**.

---

## 🌟 Nuove Funzionalità Pro

### 1. 🎟️ Link di Invito Monouso (Accesso Singolo)
* Solo l'amministratore (il proprietario del bot) può creare link di invito tramite il pulsante **`🎟️ Genera Link Invito Amico (Monouso)`** o il comando `/invito`.
* Il bot genera un link univoco: `https://t.me/prezzitrenibot?start=inv_XXXXXX`.
* **Accesso Singolo Impossibile da Condividere:** il link funziona per **1 sola persona**. Non appena l'amico clicca e preme **Avvia**, il codice di invito viene disattivato per sempre. Se inoltrato ad altri, il bot respingerà i nuovi tentativi con `Accesso Negato`.
* Notifiche automatiche all'Admin all'ingresso di ogni nuovo amico autorizzato.
* Notifiche allarmi posti/prezzi trasmesse in **broadcast a tutti gli amici autorizzati**.

### 2. 🚉 Gestione Multi-Tratta & Scelta Libera ("Fai il Pro")
Tramite il pulsante **`🚉 Cambia Tratta / Ritorno`** (o comando `/tratta`):
* **Tratte Rapide Preconfigurate (1 tap):**
  * 🚆 **Torino Porta Nuova ➔ Termoli** (Andata)
  * 🚆 **Termoli ➔ Torino Porta Nuova** (Ritorno)
  * 🚅 **Torino Porta Nuova ➔ Benevento**
  * 🚅 **Benevento ➔ Torino Porta Nuova** (Ritorno)
* **🔄 Inverti Direzione (Andata ⇄ Ritorno):** Inverte istantaneamente la partenza e l'arrivo della tratta attiva con un solo tocco!
* **🗺️ Scelta Libera di Qualsiasi Stazione d'Italia:**
  * Puoi scrivere qualsiasi città (es. *Milano, Roma, Bologna, Firenze, Napoli, Benevento, Bari, Palermo, ecc.*).
  * Il bot ricerca le stazioni ufficiali in tempo reale e configura la nuova tratta!

### 3. 🔍 Scegli Giorno & Treno Interattivo
* Invia una data (es. `21/12/2026` o tocca i pulsanti rapidi) per visualizzare tutti i treni della giornata con orari, tipo e prezzo.
* Clicca su **`[🎯 Seleziona Treno]`** per avviare il monitoraggio automatico di quel treno ogni 30 minuti!

### 4. 📊 Riepilogo Posti & Cuccette
* Visualizza posti a sedere, cuccette 4 posti (promiscuo e donna), vagoni letto e prezzi base aggiornati in tempo reale.

---

## 📁 Struttura File

```text
├── server_render.py      # Server Web con auto-ping 24/7 per Render.com
├── monitor_treni.py       # Motore Telegram con inviti monouso e multi-tratta
├── trenitalia_client.py   # Client API LeFrecce e ViaggiaTreno
├── notifier.py            # Notifiche broadcast a tutti gli utenti autorizzati
├── config.json            # Configurazione e registro inviti attivi
├── requirements.txt       # requests>=2.31.0
├── render.yaml            # Blueprint di Render
├── LICENSE                # Licenza MIT
└── README.md              # Documentazione
```

---

## 💬 Comandi Rapidi su Telegram

* `/menu` o `/start` : Mostra il pannello di controllo touch
* `/invito` : Genera un nuovo link di invito monouso per un amico (solo Admin)
* `/utenti` : Elenco di tutti gli utenti autorizzati (solo Admin)
* `/tratta` : Menu di selezione tratta (rapida, ritorno, swap o libera)
* `/stato` : Situazione posti e prezzi del treno attuale
* `/cerca [data]` : Ricerca treni per una data (es: `/cerca 21/12/2026`)
* `/frequenza` : Modifica intervallo tra i controlli (10, 15, 30, 60 min)
* `/pausa` / `/riprendi` : Sospende o riattiva il monitoraggio
* `/live` : Ritardo e binario in tempo reale (ViaggiaTreno)

---

## ☁️ Deploy su Render.com (24/7 Gratis)
Basta collegare il repository GitHub su **Render.com** (Web Service, runtime Python, startCommand `python server_render.py`). L'auto-ping integrato manterrà il servizio sveglio 24 ore su 24 senza che tu debba tenere il PC acceso.
