"""
====================================================================
  BOT MONITORAGGIO TRENITALIA CON CONTROLLO TOTALE VIA TELEGRAM
  - Selezione data e lista interattiva treni con pulsanti Telegram
  - Controllo accessi privato (blocco estranei)
  - Gestione remota totale: stato, frequenza, pausa/riprendi, live
  - Monitoraggio automatico in background con notifiche push
====================================================================
"""

import os
import re
import sys
import time
import json
import argparse
import datetime
import requests
from typing import Dict, Any, Optional, List

from trenitalia_client import TrenitaliaClient
from notifier import Notifier

# Assicura il corretto encoding UTF-8 per console Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_state.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.log")

# Stato temporaneo dell'utente (per conversazioni multi-step su Telegram)
USER_STATES: Dict[str, str] = {}


def load_config() -> Dict[str, Any]:
    """Carica la configurazione dal file config.json."""
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"File di configurazione non trovato: {CONFIG_FILE}")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: Dict[str, Any]):
    """Salva la configurazione su config.json."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def load_last_state() -> Optional[Dict[str, Any]]:
    """Carica l'ultimo stato salvato."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_state(state: Dict[str, Any]):
    """Salva lo stato corrente su file per i confronti futuri."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Errore nel salvataggio dello stato: {e}")


def write_log(message: str):
    """Accoda un messaggio nel file di log."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{now_str}] {message}\n")


def normalize_date(s: str) -> Optional[str]:
    """Normalizza varie rappresentazioni di date in formato YYYY-MM-DD."""
    s = s.strip()
    # YYYY-MM-DD o YYYY/MM/DD
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # DD-MM-YYYY o DD/MM/YYYY
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", s)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    # DD-MM o DD/MM (assume anno 2026)
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})$", s)
    if m:
        return f"2026-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def print_banner(config: Dict[str, Any]):
    """Stampa l'intestazione grafica del bot in console."""
    tr = config.get("treno", {})
    mon = config.get("monitoraggio", {})
    tg = config.get("notifiche_telegram", {})
    sec = config.get("sicurezza", {})

    tg_status = "ATTIVO ✅" if tg.get("abilitato") and tg.get("bot_token") else "DISABILITATO ❌"
    owner_status = f"ID: {sec.get('admin_chat_id')}" if sec.get("admin_chat_id") else "IN ATTESA PRIMO AVVIO 🔓"

    print("=" * 72)
    print(" 🚆 BOT TRENITALIA TELEGRAM FULL-CONTROL")
    print(f"    Treno Attivo:  {tr.get('categoria', 'ICN')} {tr.get('numero', '757')}")
    print(f"    Tratta:        {tr.get('stazione_partenza')} ➔ {tr.get('stazione_arrivo')}")
    print(f"    Data Viaggio:  {tr.get('data_viaggio')} (ore {tr.get('orario_partenza_previsto')})")
    print(f"    Monitoraggio:  {'ATTIVO ▶️' if mon.get('attivo', True) else 'IN PAUSA ⏸️'} (ogni {mon.get('intervallo_minuti', 30)} min)")
    print(f"    Telegram:      {tg_status} | Proprietario: {owner_status}")
    print("=" * 72)


def print_train_summary(train_data: Dict[str, Any]):
    """Stampa a schermo una tabella dettagliata della situazione attuale."""
    print(f"\n📊 RIEPILOGO STATO TRENO:")
    print(f"   Tratta:        {train_data.get('origine')} ➔ {train_data.get('destinazione')}")
    print(f"   Orari:         Partenza {train_data.get('orario_partenza')} | Arrivo {train_data.get('orario_arrivo')} ({train_data.get('durata')})")
    print(f"   Stato Vendite: {train_data.get('stato_vendita')}")
    print(f"   Prezzo Base:   {train_data.get('prezzo_minimo', 'N/D')} €")
    print(f"\n💺 DISPONIBILITÀ PER TIPOLOGIA DI POSTO:")
    print("   " + "-" * 64)
    print(f"   {'SERVIZIO / TIPOLOGIA':<40} | {'STATO':<10} | {'POSTI':<6} | {'PREZZO':<8}")
    print("   " + "-" * 64)

    for srv in train_data.get("servizi", []):
        s_name = srv.get("servizio", "Posto")
        display_name = s_name.replace("Posto a sedere ", "Sedile ").replace("Cuccetta Comfort ", "Cuccetta ")
        if len(display_name) > 38:
            display_name = display_name[:35] + "..."

        for off in srv.get("offerte", []):
            st = off.get("stato", "N/D")
            pst = str(off.get("posti_disponibili", "0"))
            prz = f"{off.get('prezzo')} €" if off.get("prezzo") else "N/D"
            print(f"   {display_name:<40} | {st:<10} | {pst:<6} | {prz:<8}")

    print("   " + "-" * 64 + "\n")


def build_telegram_summary(train_data: Dict[str, Any], travel_date: str) -> str:
    """Formatta la situazione del treno in HTML chiaro per Telegram."""
    lines = [
        f"🚆 <b>{train_data.get('treno_categoria', 'Treno')} {train_data.get('treno_numero')}</b>",
        f"📅 <b>Data Viaggio:</b> <code>{travel_date}</code>",
        f"📍 <b>Tratta:</b> {train_data.get('origine')} ➔ {train_data.get('destinazione')}",
        f"⏰ <b>Orari:</b> Partenza {train_data.get('orario_partenza')} | Arrivo {train_data.get('orario_arrivo')} ({train_data.get('durata')})",
        f"🎟️ <b>Stato Vendite:</b> <code>{train_data.get('stato_vendita')}</code>",
        f"💶 <b>Prezzo a partire da:</b> <b>{train_data.get('prezzo_minimo', 'N/D')} €</b>\n",
        "<b>💺 Disponibilità Dettagliata:</b>"
    ]

    for srv in train_data.get("servizi", []):
        s_name = srv.get("servizio", "Posto")
        for off in srv.get("offerte", []):
            st = off.get("stato", "")
            pst = off.get("posti_disponibili", 0)
            prz = f"{off.get('prezzo')} €" if off.get("prezzo") else "N/D"

            if st == "SALEABLE" and pst > 0:
                icon = "🟢" if pst > 5 else "🟡"
            else:
                icon = "🔴"

            lines.append(f"{icon} <b>{s_name}</b>: {pst} posti ({prz})")

    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    lines.append(f"\n<i>Ultimo controllo: ore {now_str}</i>")
    return "\n".join(lines)


def fetch_train_data(client: TrenitaliaClient, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Estrae i dati freschi del treno target dall'API Trenitalia."""
    treno_cfg = config.get("treno", {})
    data_viaggio = treno_cfg.get("data_viaggio", "2026-12-21")
    norm_date = normalize_date(str(data_viaggio)) or "2026-12-21"
    orario_dep = str(treno_cfg.get("orario_partenza_previsto", "20:50"))

    origin_id = treno_cfg.get("id_partenza", 830000219)
    arrival_id = treno_cfg.get("id_arrivo", 830011019)
    target_num = str(treno_cfg.get("numero", "757")).strip()

    # Determina l'orario di partenza per l'interrogazione
    times_to_check = [f"{norm_date}T04:00:00.000+01:00"]
    try:
        hour_part = int(orario_dep.split(":")[0]) if ":" in orario_dep else int(orario_dep)
        check_hour = max(0, hour_part - 1)
        times_to_check.insert(0, f"{norm_date}T{check_hour:02d}:00:00.000+01:00")
    except Exception:
        pass

    for t_iso in times_to_check:
        for off in [0, 10]:
            solutions_data = client.get_solutions(origin_id, arrival_id, t_iso, offset=off, limit=10)
            if solutions_data:
                found = client.find_target_train(solutions_data, target_num)
                if found:
                    return found

    return None


def check_train(client: TrenitaliaClient, notifier: Notifier, config: Dict[str, Any], is_interactive: bool = False):
    """
    Esegue il controllo periodico programmato del treno.
    Se rileva variazioni (posti liberati, calo posti, cambio prezzo) invia le notifiche push.
    """
    mon_cfg = config.get("monitoraggio", {})
    if not mon_cfg.get("attivo", True) and not is_interactive:
        notifier.log("Monitoraggio attualmente in PAUSA. Nessun controllo automatico.", "[PAUSA]")
        return

    treno_cfg = config.get("treno", {})
    threshold = mon_cfg.get("avviso_sotto_soglia_posti", 5)
    data_viaggio = treno_cfg.get("data_viaggio", "2026-12-21")
    target_num = treno_cfg.get("numero", "757")

    notifier.log(f"Controllo Trenitalia per treno {target_num} del {data_viaggio}...", "[INFO]")
    train_data = fetch_train_data(client, config)

    if not train_data:
        notifier.log(f"Treno {target_num} non trovato o server Trenitalia occupato. Riprovo al prossimo ciclo.", "[WARN]")
        write_log("ERRORE: Treno non trovato o nessuna risposta.")
        return

    print_train_summary(train_data)

    last_state = load_last_state()
    changes = []
    alerts = []

    if last_state is None:
        notifier.log("Primo avvio: stato iniziale memorizzato con successo.", "[INFO]")
        save_state(train_data)
        write_log(f"Inizializzato stato: Stato={train_data.get('stato_vendita')}, Prezzo={train_data.get('prezzo_minimo')}€")

        title = f"🚆 Monitor Attivo: {train_data.get('treno_categoria')} {target_num} ({data_viaggio})"
        msg = (
            f"Stato: {train_data.get('stato_vendita')}\n"
            f"Prezzo base: {train_data.get('prezzo_minimo')} €\n"
            f"Partenza: {train_data.get('orario_partenza')} -> {train_data.get('orario_arrivo')}"
        )
        if mon_cfg.get("notifica_ogni_controllo", False) or is_interactive:
            tg_html = build_telegram_summary(train_data, data_viaggio)
            notifier.notify(title, msg, is_alert=False, full_details_html=tg_html)
        return

    # 1. Controllo cambio stato generale di vendita
    old_status = last_state.get("stato_vendita")
    new_status = train_data.get("stato_vendita")
    if old_status != new_status:
        if new_status == "SALEABLE":
            alerts.append(f"🎉 VENDITE APERTE! Il treno è ora ACQUISTABILE! (Era: {old_status})")
        elif new_status == "SOLD_OUT":
            alerts.append("⚠️ TRENO ESAURITO! Nessun biglietto più disponibile.")
        else:
            changes.append(f"Stato vendite cambiato: da {old_status} a {new_status}")

    # 2. Controllo variazione di prezzo minimo
    old_price = last_state.get("prezzo_minimo")
    new_price = train_data.get("prezzo_minimo")
    if old_price is not None and new_price is not None and old_price != new_price:
        if new_price < old_price:
            alerts.append(f"💰 PREZZO SCESO! Da {old_price}€ a {new_price}€!")
        else:
            changes.append(f"Prezzo aumentato: da {old_price}€ a {new_price}€")

    # 3. Controllo posti per ciascun servizio
    old_services_map = {}
    for srv in last_state.get("servizi", []):
        for off in srv.get("offerte", []):
            key = f"{srv.get('servizio')}::{off.get('nome_offerta')}"
            old_services_map[key] = {
                "stato": off.get("stato"),
                "posti": off.get("posti_disponibili", 0),
                "prezzo": off.get("prezzo")
            }

    for srv in train_data.get("servizi", []):
        for off in srv.get("offerte", []):
            key = f"{srv.get('servizio')}::{off.get('nome_offerta')}"
            old_info = old_services_map.get(key)
            new_st = off.get("stato")
            new_pst = off.get("posti_disponibili", 0)
            srv_name = srv.get("servizio")

            if old_info:
                old_st = old_info.get("stato")
                old_pst = old_info.get("posti", 0)

                # Si è liberato un posto prima esaurito
                if old_st == "SOLD_OUT" and new_st == "SALEABLE":
                    alerts.append(f"🟢 SI È LIBERATO UN POSTO in '{srv_name}'! Posti: {new_pst}")
                
                # Variazione numero posti
                elif old_pst != new_pst:
                    if new_pst < old_pst:
                        diff = old_pst - new_pst
                        changes.append(f"Posti venduti per '{srv_name}': rimasti {new_pst} (-{diff})")
                        if new_pst <= threshold and new_pst > 0:
                            alerts.append(f"🚨 ULTIMI POSTI DISPONIBILI in '{srv_name}': ne restano solo {new_pst}!")
                    else:
                        diff = new_pst - old_pst
                        alerts.append(f"✨ Nuovi posti disponibili per '{srv_name}': saliti a {new_pst} (+{diff})")

    save_state(train_data)

    if alerts or changes:
        notifier.log(f"Rilevate {len(alerts)} notifiche urgenti e {len(changes)} variazioni!", "[ATTENZIONE]")
        full_text = ""
        if alerts:
            full_text += "\n".join(alerts) + "\n"
        if changes:
            full_text += "\n".join(changes)

        write_log(f"VARIAZIONI RILEVATE:\n{full_text}")

        tg_html = f"🚆 <b>AGGIORNAMENTO TRENO {target_num} ({data_viaggio})</b>\n\n"
        if alerts:
            tg_html += "<b>🚨 AVVISI IMPORTANTI:</b>\n" + "\n".join([f"• {a}" for a in alerts]) + "\n\n"
        if changes:
            tg_html += "<b>ℹ️ Dettagli:</b>\n" + "\n".join([f"• {c}" for c in changes]) + "\n\n"
        tg_html += f"<i>Partenza: {train_data.get('orario_partenza')} | Prezzo da: {train_data.get('prezzo_minimo')}€</i>"

        notifier.notify(
            title=f"🚨 Novità Treno {target_num} ({data_viaggio})",
            message=full_text.strip(),
            is_alert=len(alerts) > 0,
            full_details_html=tg_html
        )
    else:
        notifier.log("Nessuna variazione rispetto all'ultimo controllo. Tutto invariato.", "[OK]")
        write_log("Controllo completato: nessuna variazione.")
        if mon_cfg.get("notifica_ogni_controllo", False):
            tg_html = build_telegram_summary(train_data, data_viaggio)
            notifier.notify(
                title=f"Treno {target_num} - Tutto invariato",
                message=f"Posti e prezzi stabili per il {data_viaggio}.",
                is_alert=False,
                full_details_html=tg_html
            )


# ====================================================================
#   GESTIONE COMPLETA TELEGRAM & CONTROLLO ACCESSI PRIVATO
# ====================================================================

def send_tg_msg(token: str, chat_id: str, text: str, reply_markup: Optional[Dict] = None) -> bool:
    """Invia un messaggio Telegram formattato in HTML con eventuale tastiera inline."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=8)
        return r.status_code == 200
    except Exception:
        return False


def answer_tg_callback(token: str, callback_id: str, text: Optional[str] = None):
    """Risponde alla pressione di un pulsante inline per togliere l'animazione di caricamento."""
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass


def get_main_menu_keyboard(config: Dict[str, Any]) -> Dict[str, Any]:
    """Genera i pulsanti interattivi del menu principale."""
    is_active = config.get("monitoraggio", {}).get("attivo", True)
    pause_text = "⏸️ Metti in Pausa" if is_active else "▶️ Riprendi Monitoraggio"
    pause_cmd = "cmd_pause" if is_active else "cmd_resume"

    return {
        "inline_keyboard": [
            [
                {"text": "📊 Stato Treno Attuale", "callback_data": "cmd_status"},
                {"text": "🔍 Scegli Giorno & Treno", "callback_data": "cmd_search_date"}
            ],
            [
                {"text": "⏱️ Frequenza Controlli", "callback_data": "cmd_frequency"},
                {"text": pause_text, "callback_data": pause_cmd}
            ],
            [
                {"text": "📡 ViaggiaTreno Live", "callback_data": "cmd_live"},
                {"text": "ℹ️ Guida & Info", "callback_data": "cmd_help"}
            ]
        ]
    }


def send_main_menu(token: str, chat_id: str, config: Dict[str, Any], extra_text: str = ""):
    """Mostra il menu comandi principale con pulsantiera touch."""
    tr = config.get("treno", {})
    mon = config.get("monitoraggio", {})
    stato_mon = "🟢 ATTIVO" if mon.get("attivo", True) else "🟡 IN PAUSA"

    msg = ""
    if extra_text:
        msg += f"{extra_text}\n\n"

    msg += (
        "🎛️ <b>PANNELLO DI CONTROLLO TRENI</b>\n"
        f"• <b>Treno Seguito:</b> <code>{tr.get('categoria')} {tr.get('numero')}</code>\n"
        f"• <b>Tratta:</b> {tr.get('stazione_partenza')} ➔ {tr.get('stazione_arrivo')}\n"
        f"• <b>Data:</b> <code>{tr.get('data_viaggio')}</code> (ore {tr.get('orario_partenza_previsto')})\n"
        f"• <b>Stato:</b> {stato_mon} (ogni {mon.get('intervallo_minuti', 30)} min)\n\n"
        "<i>Tocca un'opzione qui sotto:</i>"
    )
    send_tg_msg(token, chat_id, msg, get_main_menu_keyboard(config))


def check_access(sender_id: str, sender_name: str, config: Dict[str, Any], token: str) -> bool:
    """
    Controllo accessi per la privacy:
    - Se admin_chat_id è vuoto: il primo utente che interagisce diventa il PROPRIETARIO UNICO.
    - Se impostato: blocca qualsiasi estraneo con messaggio di accesso negato.
    """
    sec = config.setdefault("sicurezza", {})
    admin_id = str(sec.get("admin_chat_id", "")).strip()

    # Primo utente che avvia il bot -> diventa il proprietario
    if not admin_id:
        admin_id = str(sender_id)
        sec["admin_chat_id"] = admin_id
        config["notifiche_telegram"]["chat_id"] = admin_id
        save_config(config)

        print(f"\n👑 [SICUREZZA] Registrato nuovo PROPRIETARIO UNICO: {sender_name} (ID: {admin_id})")
        write_log(f"SICUREZZA: {sender_name} (ID: {admin_id}) registrato come proprietario.")

        welcome_admin = (
            f"👑 <b>BENVENUTO {sender_name}!</b>\n\n"
            "Sei stato registrato come <b>UNICO PROPRIETARIO E AMMINISTRATORE</b> di questo bot.\n"
            "🛡️ <b>Accesso Privato Attivato:</b> nessun altro utente potrà vedere le tue tratte o modificare i treni!\n\n"
            "Puoi gestire tutto comodamente dai pulsanti qui sotto."
        )
        send_main_menu(token, sender_id, config, extra_text=welcome_admin)
        return True

    # Verifica autorizzazione
    if str(sender_id) == admin_id:
        return True

    # Utente non autorizzato
    if sec.get("blocco_altri_utenti", True):
        print(f"⛔ [SICUREZZA] Bloccato tentativo di accesso da utente estraneo: {sender_name} (ID: {sender_id})")
        write_log(f"SICUREZZA: Accesso negato per {sender_name} (ID: {sender_id})")
        send_tg_msg(
            token,
            sender_id,
            "⛔ <b>ACCESSO NEGATO</b>\n\nQuesto bot è privato ed è configurato per l'uso esclusivo del suo proprietario."
        )
        return False

    return False


def handle_search_date(client: TrenitaliaClient, token: str, chat_id: str, config: Dict[str, Any], date_input: str):
    """Esegue la ricerca dei treni per una data specifica e invia la lista con pulsanti di selezione."""
    date_normalized = normalize_date(date_input)
    if not date_normalized:
        send_tg_msg(
            token,
            chat_id,
            "❌ <b>Formato data non valido!</b>\nInserisci la data nel formato <code>GG/MM/AAAA</code> (es. <code>21/12/2026</code>):"
        )
        return

    tr = config.get("treno", {})
    orig_id = tr.get("id_partenza", 830000219)
    dest_id = tr.get("id_arrivo", 830011019)
    orig_name = tr.get("stazione_partenza", "Torino Porta Nuova")
    dest_name = tr.get("stazione_arrivo", "Termoli")

    send_tg_msg(token, chat_id, f"🔍 <i>Cerco tutti i treni per il <b>{date_normalized}</b> ({orig_name} ➔ {dest_name})...</i>")

    trains = client.get_day_trains_summary(orig_id, dest_id, date_normalized)
    if not trains:
        send_tg_msg(
            token,
            chat_id,
            f"ℹ️ Nessun treno trovato per il <b>{date_normalized}</b> sulla tratta {orig_name} ➔ {dest_name}.\n"
            "Verifica che i biglietti per questa data siano stati caricati da Trenitalia."
        )
        return

    # Costruzione messaggio riassuntivo
    text_lines = [
        f"📅 <b>TRENI DISPONIBILI IL {date_normalized}</b>",
        f"📍 <b>Tratta:</b> {orig_name} ➔ {dest_name}",
        f"Trovate <b>{len(trains)}</b> soluzioni di viaggio:\n"
    ]

    inline_buttons = []
    for t in trains:
        dep = t["orario_partenza"]
        arr = t["orario_arrivo"]
        desc = t["descrizione_treni"]
        num = t["numero_treno_principale"]
        cat = t["categoria_principale"]
        price = f"{t['prezzo_minimo']} €" if t['prezzo_minimo'] else "N/D"
        cambi_str = "Diretto" if t["diretto"] else f"{t['num_cambi']} cambio/i"

        text_lines.append(f"• <b>{dep} ➔ {arr}</b> | <b>{desc}</b> ({cambi_str}) da <b>{price}</b>")

        # Pulsante inline per selezionare questo specifico treno
        # callback_data: sel|<num>|<dep>|<date>|<cat>
        cb_data = f"sel|{num}|{dep}|{date_normalized}|{cat[:4]}"
        btn_label = f"🎯 Seleziona {cat} {num} ({dep})"
        inline_buttons.append([{"text": btn_label, "callback_data": cb_data}])

    # Aggiungi pulsante per tornare al menu
    inline_buttons.append([{"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}])

    full_text = "\n".join(text_lines)
    full_text += "\n\n👉 <i>Tocca il pulsante del treno che desideri monitorare:</i>"

    send_tg_msg(token, chat_id, full_text, {"inline_keyboard": inline_buttons})


def handle_telegram_events(
    client: TrenitaliaClient,
    config: Dict[str, Any],
    last_offset: Optional[int]
) -> Optional[int]:
    """
    Gestisce in tempo reale messaggi e clic sui pulsanti Telegram.
    Supporta:
    - /start, /menu
    - Clic pulsanti (callback_query)
    - Ricerca treni per data
    - Impostazione rapida frequenza
    - Pausa/Riprendi
    - Stato istantaneo
    """
    tg_cfg = config.get("notifiche_telegram", {})
    if not tg_cfg.get("abilitato"):
        return last_offset

    token = tg_cfg.get("bot_token", "").strip()
    if not token or "INSERISCI" in token:
        return last_offset

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"timeout": 1}
    if last_offset:
        params["offset"] = last_offset

    try:
        r = requests.get(url, params=params, timeout=4)
        if r.status_code != 200:
            return last_offset

        data = r.json()
        results = data.get("result", [])

        for u in results:
            last_offset = u["update_id"] + 1

            # ----------------------------------------------------
            # 1. GESTIONE PULSANTI INLINE (CALLBACK QUERY)
            # ----------------------------------------------------
            cb = u.get("callback_query")
            if cb:
                cb_id = cb.get("id")
                from_user = cb.get("from", {})
                sender_id = str(from_user.get("id", ""))
                sender_name = from_user.get("first_name", "Utente")
                data_val = cb.get("data", "")

                if not check_access(sender_id, sender_name, config, token):
                    answer_tg_callback(token, cb_id, "Accesso non autorizzato!")
                    continue

                answer_tg_callback(token, cb_id)

                if data_val == "cmd_menu":
                    send_main_menu(token, sender_id, config)

                elif data_val == "cmd_status":
                    send_tg_msg(token, sender_id, "🔍 <i>Interrogo Trenitalia per la situazione aggiornata...</i>")
                    train_data = fetch_train_data(client, config)
                    data_v = config.get("treno", {}).get("data_viaggio", "2026-12-21")
                    if train_data:
                        send_tg_msg(token, sender_id, build_telegram_summary(train_data, data_v), get_main_menu_keyboard(config))
                    else:
                        send_tg_msg(token, sender_id, "❌ Impossibile recuperare i dati del treno al momento.", get_main_menu_keyboard(config))

                elif data_val == "cmd_search_date":
                    USER_STATES[sender_id] = "WAITING_DATE"
                    date_kb = {
                        "inline_keyboard": [
                            [
                                {"text": "📅 21/12/2026", "callback_data": "date_2026-12-21"},
                                {"text": "📅 22/12/2026", "callback_data": "date_2026-12-22"}
                            ],
                            [
                                {"text": "📅 23/12/2026", "callback_data": "date_2026-12-23"},
                                {"text": "📅 20/12/2026", "callback_data": "date_2026-12-20"}
                            ],
                            [
                                {"text": "🔙 Annulla", "callback_data": "cmd_menu"}
                            ]
                        ]
                    }
                    send_tg_msg(
                        token,
                        sender_id,
                        "📅 <b>Scegli la data di viaggio:</b>\n\n"
                        "Tocca una data rapida qui sotto oppure <b>scrivimi la data</b> in chat (es: <code>21/12/2026</code>):",
                        date_kb
                    )

                elif data_val.startswith("date_"):
                    chosen_date = data_val.replace("date_", "")
                    USER_STATES.pop(sender_id, None)
                    handle_search_date(client, token, sender_id, config, chosen_date)

                elif data_val.startswith("sel|") or data_val.startswith("sel:"):
                    if "|" in data_val:
                        parts = data_val.split("|")
                        num = parts[1]
                        dep = parts[2]
                        d_str = parts[3]
                        cat = parts[4] if len(parts) > 4 else "Treno"
                    else:
                        parts = data_val.split(":")
                        num = parts[1]
                        dep = f"{parts[2]}:{parts[3]}" if len(parts) > 3 else "20:50"
                        d_str = parts[4] if len(parts) > 4 else "2026-12-21"
                        cat = parts[5] if len(parts) > 5 else "Treno"

                    # Assicura che la data sia valida e non sia un pezzo di orario
                    if not re.match(r"^\d{4}-\d{2}-\d{2}$", d_str):
                        d_str = normalize_date(d_str) or "2026-12-21"

                    # Aggiorna la configurazione
                    config["treno"]["numero"] = num
                    config["treno"]["data_viaggio"] = d_str
                    config["treno"]["orario_partenza_previsto"] = dep
                    config["treno"]["categoria"] = "InterCityNotte" if "ICN" in cat or num in ("757", "755") else ("Frecciarossa" if "Frec" in cat else "Treno")
                    save_config(config)

                    # Cancella vecchio stato per forzare nuovo confronto
                    save_state({})
                    print(f"\n🎯 [TELEGRAM] Nuovo treno impostato dall'utente: {config['treno']['categoria']} {num} ({d_str} ore {dep})")
                    write_log(f"CONFIGURAZIONE: Impostato treno {num} per il {d_str} ore {dep}")

                    confirm_text = (
                        f"✅ <b>TRENO SELEZIONATO CON SUCCESSO!</b>\n\n"
                        f"• <b>Treno:</b> {config['treno']['categoria']} {num}\n"
                        f"• <b>Data:</b> <code>{d_str}</code>\n"
                        f"• <b>Orario:</b> ore {dep}\n\n"
                        f"Il bot ora monitora questo treno ogni {config.get('monitoraggio', {}).get('intervallo_minuti', 30)} minuti.\n"
                        "Recupero la disponibilità attuale..."
                    )
                    send_tg_msg(token, sender_id, confirm_text)

                    # Esegue subito verifica del treno scelto
                    train_data = fetch_train_data(client, config)
                    if train_data:
                        send_tg_msg(token, sender_id, build_telegram_summary(train_data, d_str), get_main_menu_keyboard(config))
                    else:
                        send_tg_msg(token, sender_id, "Monitoraggio avviato!", get_main_menu_keyboard(config))

                elif data_val == "cmd_frequency":
                    freq_kb = {
                        "inline_keyboard": [
                            [
                                {"text": "⏱️ Ogni 15 min", "callback_data": "freq_15"},
                                {"text": "⏱️ Ogni 30 min (Consigliato)", "callback_data": "freq_30"}
                            ],
                            [
                                {"text": "⏱️ Ogni 60 min", "callback_data": "freq_60"},
                                {"text": "⏱️ Ogni 10 min", "callback_data": "freq_10"}
                            ],
                            [
                                {"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}
                            ]
                        ]
                    }
                    curr = config.get("monitoraggio", {}).get("intervallo_minuti", 30)
                    send_tg_msg(token, sender_id, f"⏱️ <b>Frequenza attuale:</b> ogni {curr} minuti.\nScegli il nuovo intervallo:", freq_kb)

                elif data_val.startswith("freq_"):
                    new_freq = int(data_val.replace("freq_", ""))
                    config["monitoraggio"]["intervallo_minuti"] = new_freq
                    save_config(config)
                    send_tg_msg(token, sender_id, f"✅ Frequenza aggiornata: controllo ogni <b>{new_freq} minuti</b>!", get_main_menu_keyboard(config))

                elif data_val in ("cmd_pause", "cmd_resume"):
                    new_state = (data_val == "cmd_resume")
                    config["monitoraggio"]["attivo"] = new_state
                    save_config(config)
                    txt = "▶️ Monitoraggio automatico <b>RIPRESO</b>!" if new_state else "⏸️ Monitoraggio automatico <b>SOSPESO</b>!"
                    send_tg_msg(token, sender_id, txt, get_main_menu_keyboard(config))

                elif data_val == "cmd_live":
                    target_num = config.get("treno", {}).get("numero", "757")
                    send_tg_msg(token, sender_id, f"📡 <i>Interrogo ViaggiaTreno per il treno {target_num}...</i>")
                    live = client.get_viaggiatreno_live(target_num)
                    if live:
                        live_msg = (
                            f"📡 <b>TRENO {live.get('numero')} IN TEMPO REALE</b>\n\n"
                            f"Origine: {live.get('origine')} ➔ Destinazione: {live.get('destinazione')}\n"
                            f"⏱️ <b>Ritardo:</b> {live.get('ritardo', 0)} minuti\n"
                            f"📍 <b>Posizione:</b> {live.get('stazione_ultimo_rilevamento')}\n"
                        )
                        if live.get("binario_effettivo_partenza"):
                            live_msg += f"🚉 <b>Binario Partenza:</b> {live.get('binario_effettivo_partenza')}\n"
                    else:
                        live_msg = f"ℹ️ Nessun dato in tempo reale disponibile per il treno {target_num} in questo momento (parte alle 20:50)."
                    send_tg_msg(token, sender_id, live_msg, get_main_menu_keyboard(config))

                elif data_val == "cmd_help":
                    help_text = (
                        "📖 <b>GUIDA COMANDI BOT TRENITALIA</b>\n\n"
                        "Puoi gestire tutto con i pulsanti touch oppure con questi comandi:\n"
                        "• <b>/menu</b> : Mostra il pannello pulsanti principale\n"
                        "• <b>/stato</b> : Controlla posti liberi e prezzi aggiornati adesso\n"
                        "• <b>/cerca [data]</b> : Mostra i treni di un giorno e ti fa scegliere quale seguire (es: <code>/cerca 21/12/2026</code>)\n"
                        "• <b>/treno [numero]</b> : Cambia direttamente il numero treno (es: <code>/treno 757</code>)\n"
                        "• <b>/frequenza [minuti]</b> : Cambia tempo tra i controlli (es: <code>/frequenza 15</code>)\n"
                        "• <b>/pausa</b> / <b>/riprendi</b> : Sospende o riattiva i controlli in background\n"
                        "• <b>/live</b> : Verifica ritardo e binario in tempo reale"
                    )
                    send_tg_msg(token, sender_id, help_text, get_main_menu_keyboard(config))

                continue

            # ----------------------------------------------------
            # 2. GESTIONE MESSAGGI DI TESTO
            # ----------------------------------------------------
            msg = u.get("message")
            if not msg:
                continue

            sender_id = str(msg.get("chat", {}).get("id", ""))
            sender_name = msg.get("from", {}).get("first_name", "Utente")
            text = msg.get("text", "").strip()

            if not check_access(sender_id, sender_name, config, token):
                continue

            # Se l'utente era in attesa di inserire una data
            if USER_STATES.get(sender_id) == "WAITING_DATE":
                USER_STATES.pop(sender_id, None)
                handle_search_date(client, token, sender_id, config, text)
                continue

            text_low = text.lower()

            if text_low in ("/start", "/menu", "menu", "ciao", "start"):
                send_main_menu(token, sender_id, config)

            elif text_low in ("/stato", "stato", "/controlla", "controlla", "prezzo"):
                send_tg_msg(token, sender_id, "🔍 <i>Controllo Trenitalia in corso...</i>")
                train_data = fetch_train_data(client, config)
                data_v = config.get("treno", {}).get("data_viaggio", "2026-12-21")
                if train_data:
                    send_tg_msg(token, sender_id, build_telegram_summary(train_data, data_v), get_main_menu_keyboard(config))
                else:
                    send_tg_msg(token, sender_id, "❌ Impossibile recuperare i dati al momento.", get_main_menu_keyboard(config))

            elif text_low.startswith("/cerca"):
                parts = text.split(maxsplit=1)
                if len(parts) > 1:
                    handle_search_date(client, token, sender_id, config, parts[1])
                else:
                    USER_STATES[sender_id] = "WAITING_DATE"
                    send_tg_msg(
                        token,
                        sender_id,
                        "📅 Invia la data del viaggio nel formato <code>GG/MM/AAAA</code> (es: <code>21/12/2026</code>):"
                    )

            elif text_low.startswith("/treno"):
                parts = text.split(maxsplit=1)
                if len(parts) > 1:
                    t_num = parts[1].strip()
                    config["treno"]["numero"] = t_num
                    save_config(config)
                    save_state({})
                    send_tg_msg(token, sender_id, f"✅ Treno impostato su <b>{t_num}</b>!", get_main_menu_keyboard(config))
                else:
                    send_tg_msg(token, sender_id, "Specifica il numero treno, es: <code>/treno 757</code>")

            elif text_low.startswith("/frequenza") or text_low.startswith("/intervallo"):
                parts = text.split(maxsplit=1)
                if len(parts) > 1 and parts[1].strip().isdigit():
                    new_f = int(parts[1].strip())
                    config["monitoraggio"]["intervallo_minuti"] = new_f
                    save_config(config)
                    send_tg_msg(token, sender_id, f"✅ Frequenza impostata: ogni <b>{new_f} minuti</b>!", get_main_menu_keyboard(config))
                else:
                    send_tg_msg(token, sender_id, "Specifica i minuti, es: <code>/frequenza 15</code>")

            elif text_low in ("/pausa", "pausa"):
                config["monitoraggio"]["attivo"] = False
                save_config(config)
                send_tg_msg(token, sender_id, "⏸️ Monitoraggio automatico <b>SOSPESO</b>!", get_main_menu_keyboard(config))

            elif text_low in ("/riprendi", "/avvia", "riprendi", "avvia"):
                config["monitoraggio"]["attivo"] = True
                save_config(config)
                send_tg_msg(token, sender_id, "▶️ Monitoraggio automatico <b>RIPRESO</b>!", get_main_menu_keyboard(config))

            elif text_low in ("/live", "live", "ritardo"):
                target_num = config.get("treno", {}).get("numero", "757")
                live = client.get_viaggiatreno_live(target_num)
                if live:
                    live_msg = (
                        f"📡 <b>TRENO {live.get('numero')} IN TEMPO REALE</b>\n\n"
                        f"Origine: {live.get('origine')} ➔ Destinazione: {live.get('destinazione')}\n"
                        f"⏱️ <b>Ritardo:</b> {live.get('ritardo', 0)} minuti\n"
                        f"📍 <b>Posizione:</b> {live.get('stazione_ultimo_rilevamento')}\n"
                    )
                else:
                    live_msg = f"ℹ️ Nessun dato in tempo reale disponibile per il treno {target_num} in questo momento."
                send_tg_msg(token, sender_id, live_msg, get_main_menu_keyboard(config))

            elif text_low in ("/help", "help", "guida"):
                send_tg_msg(token, sender_id, "Tocca i pulsanti del menu per gestire il bot:", get_main_menu_keyboard(config))

            else:
                # Controlla se l'utente ha semplicemente scritto una data (es. 21/12/2026)
                date_check = normalize_date(text)
                if date_check:
                    handle_search_date(client, token, sender_id, config, date_check)
                else:
                    send_main_menu(token, sender_id, config, extra_text="Non ho riconosciuto il comando. Scegli un'opzione qui sotto:")

        return last_offset
    except Exception:
        return last_offset


def show_live_status(client: TrenitaliaClient, config: Dict[str, Any]):
    """Mostra i dati in tempo reale del treno da ViaggiaTreno in console."""
    target_num = config.get("treno", {}).get("numero", "757")
    print(f"\n📡 Connessione a ViaggiaTreno per verificare il treno {target_num} in tempo reale...")
    live = client.get_viaggiatreno_live(target_num)
    if not live:
        print(f"❌ Nessuna informazione in tempo reale per il treno {target_num} al momento (parte alle 20:50).")
        return

    print("=" * 60)
    print(f" 🚆 STATO IN TEMPO REALE - TRENO {live.get('numero')}")
    print(f"    Tratta:       {live.get('origine')} ➔ {live.get('destinazione')}")
    print(f"    Ritardo:      {live.get('ritardo', 0)} minuti")
    print(f"    Posizione:    {live.get('stazione_ultimo_rilevamento')}")
    if live.get("binario_effettivo_partenza"):
        print(f"    Binario Part: {live.get('binario_effettivo_partenza')}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Bot Trenitalia con controllo completo da Telegram")
    parser.add_argument("--check-now", action="store_true", help="Esegue un solo controllo immediato ed esce")
    parser.add_argument("--live", action="store_true", help="Mostra lo stato in tempo reale da ViaggiaTreno")
    parser.add_argument("--interval", type=int, help="Imposta l'intervallo di monitoraggio in minuti")
    parser.add_argument("--test-notify", action="store_true", help="Invia una notifica di prova")
    args = parser.parse_args()

    config = load_config()
    notifier = Notifier(config)
    client = TrenitaliaClient()

    print_banner(config)

    if args.test_notify:
        print("\n🧪 Invio notifica di prova su tutti i canali configurati...")
        notifier.notify(
            title="🚆 Prova Notifiche Trenitalia Bot",
            message="Se vedi questo messaggio, il sistema di notifiche funziona perfettamente!",
            is_alert=True
        )
        return

    if args.live:
        show_live_status(client, config)
        return

    if args.check_now:
        check_train(client, notifier, config, is_interactive=True)
        return

    # Inizializza l'offset di Telegram
    telegram_offset = None
    tg_token = config.get("notifiche_telegram", {}).get("bot_token", "").strip()
    if tg_token:
        try:
            r = requests.get(f"https://api.telegram.org/bot{tg_token}/getUpdates", timeout=5)
            updates = r.json().get("result", [])
            if updates:
                telegram_offset = updates[-1]["update_id"] + 1
        except Exception:
            pass

    intervallo_min = args.interval if args.interval else config.get("monitoraggio", {}).get("intervallo_minuti", 30)

    print(f"\n🚀 BOT ATTIVO IN BACKGROUND!")
    print(f"   • Controllo automatico: ogni {intervallo_min} minuti")
    print(f"   • Ricezione comandi Telegram: ATTIVA in tempo reale (apri @Prezzotrenibot)")
    print("   Premi [CTRL+C] per arrestare il bot.\n")

    try:
        ciclo = 1
        while True:
            # Ricarica configurazione fresca (per recepire eventuali cambi via Telegram)
            config = load_config()
            notifier = Notifier(config)
            intervallo_min = config.get("monitoraggio", {}).get("intervallo_minuti", 30)
            intervallo_sec = intervallo_min * 60

            print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] --- CICLO DI CONTROLLO #{ciclo} ---")
            check_train(client, notifier, config)

            prossimo = datetime.datetime.now() + datetime.timedelta(seconds=intervallo_sec)
            print(f"⏳ In ascolto su Telegram... Prossimo controllo automatico alle ore {prossimo.strftime('%H:%M:%S')} (tra {intervallo_min} min)...")

            # Loop di ascolto Telegram ad alta reattività (risponde in ~1 secondo)
            sleep_start = time.time()
            last_event_check = 0

            while time.time() - sleep_start < intervallo_sec:
                if time.time() - last_event_check >= 1.0:
                    config = load_config()  # Mantiene config sincronizzato
                    telegram_offset = handle_telegram_events(client, config, telegram_offset)
                    last_event_check = time.time()
                time.sleep(0.2)

            ciclo += 1

    except KeyboardInterrupt:
        print("\n\n🛑 Bot arrestato dall'utente. Arrivederci!")


if __name__ == "__main__":
    main()
