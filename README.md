# 🚆 Bot Monitor Trenitalia 24/7 (Telegram & Cloud Ready)

Bot in Python per monitorare la disponibilità dei posti, aperture delle vendite e variazioni di prezzo dei treni **Trenitalia** (incluso l'**Intercity Notte 757** Torino ➔ Termoli).

Progettato con **controllo completo da Telegram** e pronto per l'hosting continuo **24 ore su 24 gratuito su Render.com** (o locale su PC).

---

## ✨ Caratteristiche Principali

* 📱 **Controllo Totale da Telegram:**
  * **Scegli giorno e treno:** Invia una data (es. `21/12/2026`) per ricevere la lista di tutti i treni della giornata con pulsanti touch `[🎯 Seleziona Treno]`.
  * **Riepilogo Dettagliato Posti:** Mostra posti a sedere, cuccette 4 posti (promiscuo/donna), vagoni letto e prezzi aggiornati in 2 secondi.
  * **Gestione Frequenza:** Cambia l'intervallo dei controlli (10, 15, 30 o 60 min) con un tap.
  * **Pausa e Ripresa:** Metti in pausa o riavvia i controlli quando vuoi.
  * **ViaggiaTreno Live:** Verifica ritardi e binari in tempo reale.
* 🛡️ **Accesso Privato Esclusivo:** Solo il proprietario (riconosciuto al primo avvio) può interagire con il bot; gli estranei vengono respinti con `Accesso Negato`.
* 🔔 **Allarmi Intelligenti:** Notifiche push automatiche se si libera un posto prima esaurito, se i posti scendono sotto soglia di emergenza (es. $\le 5$) o se cambia il prezzo base.
* ☁️ **Deploy Cloud 24/7 (Render):** Include server web leggero con auto-ping keep-alive per funzionare a computer spento senza andare in standby.

---

## 📂 Struttura del Progetto

```text
├── server_render.py      # Server Web con auto-ping 24/7 per il deploy su Render.com
├── monitor_treni.py       # Motore principale di monitoraggio e ascolto Telegram
├── trenitalia_client.py   # Client HTTP per le API ufficiali LeFrecce e ViaggiaTreno
├── notifier.py            # Gestione notifiche (Telegram, Windows Toast, Audio)
├── config.json            # Configurazione (token bot, tratte, soglie e preferenze)
├── requirements.txt       # Dipendenze Python (requests)
├── render.yaml            # Configurazione Blueprint per Render.com
├── avvia_bot.bat          # Launcher rapido per Windows con menu interattivo
├── carica_su_github.bat   # Script per caricamento su GitHub
├── LICENSE                # Licenza MIT
└── README.md              # Documentazione del progetto
```

---

## ☁️ Deploy su Render.com (24/7 a PC Spento)

1. Collega il repository a **[Render.com](https://dashboard.render.com)**.
2. Clicca su **New +** ➔ **Web Service**.
3. Seleziona questo repository.
4. Render leggerà automaticamente il file `render.yaml` e `server_render.py`.
5. Clicca su **Create Web Service**: il bot sarà operativo nel cloud in 60 secondi!

---

## 💻 Esecuzione in Locale su PC (Windows)

Fai doppio clic sul file **`avvia_bot.bat`** sul Desktop per aprire il menu rapido:
* `[1]` Avvia monitoraggio continuo ogni 30 minuti
* `[2]` Controllo istantaneo singolo
* `[3]` Prova notifiche
* `[4]` Stato ViaggiaTreno in tempo reale
* `[5]` Configurazione guidata Telegram

Oppure da terminale:
```bash
pip install -r requirements.txt
python monitor_treni.py
```

---

## 📄 Licenza

Rilasciato sotto licenza [MIT](LICENSE). Realizzato per uso personale e di studio.
