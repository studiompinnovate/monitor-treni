"""
====================================================================
  BOT MONITOR TRENI PRO (TRENITALIA & ITALO READY)
  - Controllo disponibilità posti, cuccette e prezzi
  - Gestione multi-tratta rapida (Torino, Termoli, Benevento, ecc.)
  - Scelta libera di qualsiasi stazione d'Italia con ricerca live
  - Accesso libero o su richiesta gestibile dal Proprietario (/menu)
  - Live ritardi e binari (Trenitalia ViaggiaTreno + Italo in Viaggio)
====================================================================
"""

import os
import re
import sys
import time
import json
import secrets
import argparse
import datetime
import requests
from typing import Dict, Any, Optional, List

from trenitalia_client import TrenitaliaClient
from notifier import Notifier

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_state.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.log")

USER_STATES: Dict[str, str] = {}
USER_TEMP_DATA: Dict[str, Dict[str, Any]] = {}

TRATTE_PRESET = {
    "torino_termoli": {
        "partenza": "Torino Porta Nuova", "id_partenza": 830000219,
        "arrivo": "Termoli", "id_arrivo": 830011019,
        "label": "Torino P.N. ➔ Termoli"
    },
    "termoli_torino": {
        "partenza": "Termoli", "id_partenza": 830011019,
        "arrivo": "Torino Porta Nuova", "id_arrivo": 830000219,
        "label": "Termoli ➔ Torino P.N. (Ritorno)"
    },
    "torino_benevento": {
        "partenza": "Torino Porta Nuova", "id_partenza": 830000219,
        "arrivo": "Benevento", "id_arrivo": 830009999,
        "label": "Torino P.N. ➔ Benevento"
    },
    "benevento_torino": {
        "partenza": "Benevento", "id_partenza": 830009999,
        "arrivo": "Torino Porta Nuova", "id_arrivo": 830000219,
        "label": "Benevento ➔ Torino P.N. (Ritorno)"
    }
}


LOCAL_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.local.json")


def load_config() -> Dict[str, Any]:
    target = LOCAL_CONFIG_FILE if os.path.exists(LOCAL_CONFIG_FILE) else CONFIG_FILE
    if not os.path.exists(target):
        raise FileNotFoundError(f"File non trovato: {target}")
    with open(target, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if env_token:
        cfg.setdefault("notifiche_telegram", {})["bot_token"] = env_token.strip()
    return cfg


def save_config(cfg: Dict[str, Any]):
    target = LOCAL_CONFIG_FILE if os.path.exists(LOCAL_CONFIG_FILE) else CONFIG_FILE
    with open(target, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def load_last_state() -> Optional[Dict[str, Any]]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_state(state: Dict[str, Any]):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Errore salvataggio stato: {e}")


def write_log(message: str):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{now_str}] {message}\n")


def normalize_date(s: str) -> Optional[str]:
    s = s.strip()
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", s)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})$", s)
    if m:
        return f"2026-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def print_banner(config: Dict[str, Any]):
    tr = config.get("treno", {})
    mon = config.get("monitoraggio", {})
    tg = config.get("notifiche_telegram", {})
    sec = config.get("sicurezza", {})

    print("=" * 72)
    print(" 🚆 BOT MONITOR TRENI PRO")
    print(f"    Treno Attivo:  {tr.get('categoria', 'Treno')} {tr.get('numero')}")
    print(f"    Tratta:        {tr.get('stazione_partenza')} ➔ {tr.get('stazione_arrivo')}")
    print(f"    Data:          {tr.get('data_viaggio')} (ore {tr.get('orario_partenza_previsto', 'N/D')})")
    print(f"    Frequenza:     Ogni {mon.get('intervallo_minuti', 30)} min | Telegram: {'ATTIVO ✅' if tg.get('abilitato') else 'DISATTIVO ❌'}")
    print(f"    Proprietario:  {sec.get('admin_chat_id', 'NON IMPOSTATO')} | Utenti Connessi: {len(sec.get('utenti_autorizzati', []))}")
    print("=" * 72)


def print_train_summary(train_data: Dict[str, Any]):
    print(f"\n📊 RIEPILOGO STATO TRENO:")
    print(f"   Tratta:        {train_data.get('origine')} ➔ {train_data.get('destinazione')}")
    print(f"   Orari:         Partenza {train_data.get('orario_partenza')} | Arrivo {train_data.get('orario_arrivo')} ({train_data.get('durata')})")
    if train_data.get("num_cambi", 0) > 0:
        print(f"   Soluzione:     {train_data.get('descrizione_soluzione')} ({train_data.get('num_cambi')} cambi)")
    print(f"   Stato Vendite: {train_data.get('stato_vendita')}")
    print(f"   Prezzo Base:   {train_data.get('prezzo_minimo')} €")

    servizi = train_data.get("servizi", [])
    if servizi:
        print(f"\n💺 DISPONIBILITÀ POSTI:")
        print("   " + "-" * 64)
        print(f"   {'SERVIZIO':<35} | {'STATO':<10} | {'POSTI':<6} | {'PREZZO MIN':<10}")
        print("   " + "-" * 64)
        for srv in servizi:
            display_name = srv.get("servizio", "Posto")[:35]
            st = srv.get("stato", "")
            pst = srv.get("posti_disponibili", 0)
            prz = f"{srv.get('prezzo_minimo')} €" if srv.get("prezzo_minimo") else "N/D"
            print(f"   {display_name:<35} | {st:<10} | {pst:<6} | {prz:<10}")
        print("   " + "-" * 64 + "\n")


def build_telegram_summary(train_data: Dict[str, Any], travel_date: str) -> str:
    lines = [
        f"🚆 <b>{train_data.get('treno_categoria', 'Treno')} {train_data.get('treno_numero')}</b>",
        f"📅 <b>Data:</b> <code>{travel_date}</code>",
        f"📍 <b>Tratta:</b> {train_data.get('origine')} ➔ {train_data.get('destinazione')}",
        f"⏰ <b>Orari:</b> {train_data.get('orario_partenza')} ➔ {train_data.get('orario_arrivo')} ({train_data.get('durata')})",
    ]

    if train_data.get("num_cambi", 0) > 0:
        lines.append(f"🔄 <b>Cambi:</b> {train_data.get('num_cambi')} ({train_data.get('descrizione_soluzione')})")

    lines.append(f"🎟️ <b>Stato Vendite:</b> <code>{train_data.get('stato_vendita')}</code>")
    lines.append(f"💶 <b>Prezzo a partire da:</b> <b>{train_data.get('prezzo_minimo', 'N/D')} €</b>\n")
    lines.append("<b>💺 Disponibilità & Tariffe:</b>")

    servizi = train_data.get("servizi", [])
    if not servizi:
        lines.append("ℹ️ <i>Dettagli sui posti non disponibili per questo treno al momento.</i>")
    else:
        for srv in servizi:
            s_name = srv.get("servizio", "Posto")
            offers = srv.get("offerte", [])
            icon_srv = "🛏️" if "cuccett" in s_name.lower() or "letto" in s_name.lower() else "💺"

            lines.append(f"\n{icon_srv} <b>{s_name}:</b>")
            if not offers:
                lines.append("   • <i>Nessuna tariffa attiva al momento</i>")
            else:
                for off in offers:
                    off_name = off.get("nome_offerta", "Tariffa")
                    st = off.get("stato", "")
                    pst = off.get("posti_disponibili", 0)
                    prz = f"{off.get('prezzo')} €" if off.get("prezzo") else "N/D"

                    if st == "SOLD_OUT" or pst == 0:
                        lines.append(f"   • <b>{off_name}:</b> 🔴 <i>Esaurito</i>")
                    elif pst > 5:
                        lines.append(f"   • <b>{off_name}:</b> 🟢 <b>{pst} posti</b> ({prz})")
                    else:
                        lines.append(f"   • <b>{off_name}:</b> 🟡 ⚠️ <b>SOLI {pst} POSTI!</b> ({prz})")

    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    lines.append(f"\n<i>Aggiornato alle ore {now_str}</i>")
    return "\n".join(lines)


def fetch_train_data(client: TrenitaliaClient, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    treno_cfg = config.get("treno", {})
    data_viaggio = treno_cfg.get("data_viaggio", "2026-12-21")
    norm_date = normalize_date(str(data_viaggio)) or "2026-12-21"
    orario_dep = str(treno_cfg.get("orario_partenza_previsto", "20:50"))

    origin_id = treno_cfg.get("id_partenza", 830000219)
    arrival_id = treno_cfg.get("id_arrivo", 830011019)
    target_num = str(treno_cfg.get("numero", "757")).strip()

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
    mon_cfg = config.get("monitoraggio", {})
    if not mon_cfg.get("attivo", True) and not is_interactive:
        notifier.log("Monitoraggio in PAUSA.", "[PAUSA]")
        return

    treno_cfg = config.get("treno", {})
    threshold = 10  # Posti in esaurimento se meno di 10
    data_viaggio = treno_cfg.get("data_viaggio", "2026-12-21")
    target_num = treno_cfg.get("numero", "757")

    notifier.log(f"Verifica (ogni 30 min): {target_num} del {data_viaggio}...", "[INFO]")
    train_data = fetch_train_data(client, config)

    if not train_data:
        notifier.log(f"Treno {target_num} non trovato al momento.", "[WARN]")
        write_log("WARN: Treno non trovato.")
        return

    print_train_summary(train_data)
    save_state(train_data)

    # Rileva SOLO posti in esaurimento (meno di 10 posti rimasti)
    esaurimento = []
    for srv in train_data.get("servizi", []):
        s_name = srv.get("servizio", "Posto")
        for off in srv.get("offerte", []):
            off_name = off.get("nome_offerta", "Tariffa")
            st = off.get("stato", "")
            pst = off.get("posti_disponibili", 0)
            prz = f"{off.get('prezzo')} €" if off.get("prezzo") else "N/D"

            if st == "SALEABLE" and 0 < pst < threshold:
                esaurimento.append(f"• <b>{s_name} ({off_name}):</b> restano solo <b>{pst} posti!</b> ({prz})")

    # Costruisce il messaggio di tracciamento
    summary_body = build_telegram_summary(train_data, data_viaggio)

    # Se ci sono posti in esaurimento (< 10), li scrive ALL'INIZIO del messaggio
    if esaurimento:
        header = (
            "🚨 <b>ATTENZIONE: POSTI IN ESAURIMENTO (< 10 RIMASTI)!</b>\n"
            + "\n".join(esaurimento)
            + "\n" + "—" * 30 + "\n\n"
        )
        full_message = header + summary_body
        is_alert = True
        write_log(f"ESAURIMENTO (<10): {len(esaurimento)} servizi sotto soglia.")
    else:
        full_message = summary_body
        is_alert = False

    # Invia il messaggio unico di tracciamento ogni mezz'ora
    notifier.notify(
        title=f"🚆 Monitor Treno {target_num}",
        message=f"Tracciamento treno {target_num}",
        is_alert=is_alert,
        full_details_html=full_message
    )


# ====================================================================
#   TELEGRAM & COMANDI & MENU
# ====================================================================

def send_tg_msg(token: str, chat_id: str, text: str, reply_markup: Optional[Dict] = None) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=8)
        return r.status_code == 200
    except Exception:
        return False


def answer_tg_callback(token: str, callback_id: str, text: str = ""):
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    try:
        requests.post(url, json=payload, timeout=4)
    except Exception:
        pass


def is_admin(sender_id: str, config: Dict[str, Any]) -> bool:
    admin_id = str(config.get("sicurezza", {}).get("admin_chat_id", "")).strip()
    return str(sender_id).strip() == admin_id


def is_user_authorized(sender_id: str, config: Dict[str, Any]) -> bool:
    sec = config.get("sicurezza", {})
    if not sec.get("blocco_altri_utenti", False):
        return True
    admin_id = str(sec.get("admin_chat_id", "")).strip()
    s_id = str(sender_id).strip()
    if s_id == admin_id:
        return True
    authorized_list = [str(x).strip() for x in sec.get("utenti_autorizzati", [])]
    return s_id in authorized_list


def get_main_menu_keyboard(config: Dict[str, Any], sender_id: str) -> Dict[str, Any]:
    """Tastiera pulita per consultazione treni, senza pulsanti amministratore o inviti."""
    is_active = config.get("monitoraggio", {}).get("attivo", True)
    pause_text = "⏸️ Metti in Pausa" if is_active else "▶️ Riprendi"
    pause_cmd = "cmd_pause" if is_active else "cmd_resume"

    kb = [
        [
            {"text": "📊 Stato Treno Attuale", "callback_data": "cmd_status"},
            {"text": "🔍 Scegli Giorno & Treno", "callback_data": "cmd_search_date"}
        ],
        [
            {"text": "🚉 Cambia Tratta / Ritorno", "callback_data": "cmd_routes"},
            {"text": "⏱️ Frequenza", "callback_data": "cmd_frequency"}
        ],
        [
            {"text": pause_text, "callback_data": pause_cmd},
            {"text": "📡 Live & Ritardi", "callback_data": "cmd_live"}
        ]
    ]
    return {"inline_keyboard": kb}


def send_main_menu(token: str, chat_id: str, config: Dict[str, Any], extra_text: str = ""):
    """Mostra la situazione attuale del treno e il menu normale dei pulsanti."""
    tr = config.get("treno", {})
    mon = config.get("monitoraggio", {})
    stato_mon = "🟢 ATTIVO" if mon.get("attivo", True) else "🟡 IN PAUSA"

    msg = ""
    if extra_text:
        msg += f"{extra_text}\n\n"

    msg += (
        "🎛️ <b>MONITOR TRENI</b>\n"
        f"• <b>Tratta:</b> <code>{tr.get('stazione_partenza')} ➔ {tr.get('stazione_arrivo')}</code>\n"
        f"• <b>Treno:</b> <code>{tr.get('categoria')} {tr.get('numero')}</code> (ore {tr.get('orario_partenza_previsto')})\n"
        f"• <b>Data:</b> <code>{tr.get('data_viaggio')}</code>\n"
        f"• <b>Monitoraggio:</b> {stato_mon} (ogni {mon.get('intervallo_minuti', 30)} min)\n\n"
        "<i>Tocca un'opzione qui sotto:</i>"
    )
    send_tg_msg(token, chat_id, msg, get_main_menu_keyboard(config, chat_id))


def send_admin_menu(token: str, chat_id: str, config: Dict[str, Any], extra_text: str = ""):
    """Menu speciale riservato esclusivamente al proprietario, richiamabile solo con /menu o /admin."""
    sec = config.get("sicurezza", {})
    is_blocked = sec.get("blocco_altri_utenti", False)
    mode_label = "🔒 Accesso: Con Approvazione" if is_blocked else "🟢 Accesso: Libero (Chi ha il link)"
    aut_users = sec.get("utenti_autorizzati", [])

    kb = [
        [
            {"text": "🎟️ Genera Link Invito Amico (Monouso)", "callback_data": "cmd_create_invite"}
        ],
        [
            {"text": f"🛡️ {mode_label}", "callback_data": "cmd_toggle_access"}
        ],
        [
            {"text": f"👥 Amici Autorizzati ({len(aut_users)})", "callback_data": "cmd_list_users"}
        ],
        [
            {"text": "🔙 Torna ai Treni", "callback_data": "cmd_menu"}
        ]
    ]

    msg = ""
    if extra_text:
        msg += f"{extra_text}\n\n"

    msg += (
        "👑 <b>PANNELLO PROPRIETARIO</b>\n\n"
        f"• <b>Modalità Accesso:</b> {'🔒 Con Approvazione' if is_blocked else '🟢 Libero a chiunque abbia il link'}\n"
        f"• <b>Amici Registrati:</b> {len(aut_users)}\n\n"
        "<i>Questo pannello è visibile solo a te digitando <code>/menu</code> o <code>/admin</code>.</i>"
    )
    send_tg_msg(token, chat_id, msg, {"inline_keyboard": kb})


def send_routes_menu(token: str, chat_id: str, config: Dict[str, Any]):
    tr = config.get("treno", {})
    kb = [
        [
            {"text": "🚆 Torino ➔ Termoli", "callback_data": "set_route_torino_termoli"},
            {"text": "🚆 Termoli ➔ Torino (Ritorno)", "callback_data": "set_route_termoli_torino"}
        ],
        [
            {"text": "🚅 Torino ➔ Benevento", "callback_data": "set_route_torino_benevento"},
            {"text": "🚅 Benevento ➔ Torino (Ritorno)", "callback_data": "set_route_benevento_torino"}
        ],
        [
            {"text": "🔄 Inverti Direzione Attuale", "callback_data": "route_swap"}
        ],
        [
            {"text": "🗺️ Scegli Qualsiasi Altra Stazione d'Italia", "callback_data": "route_custom"}
        ],
        [
            {"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}
        ]
    ]
    txt = (
        "🚉 <b>SELEZIONE TRATTA E DESTINAZIONE</b>\n\n"
        f"📍 <b>Tratta attuale:</b> <code>{tr.get('stazione_partenza')} ➔ {tr.get('stazione_arrivo')}</code>\n\n"
        "Scegli una tratta rapida oppure imposta <b>qualsiasi altra città d'Italia</b>:"
    )
    send_tg_msg(token, chat_id, txt, {"inline_keyboard": kb})


def create_single_use_invite(config: Dict[str, Any], admin_name: str) -> str:
    sec = config.setdefault("sicurezza", {})
    inviti = sec.setdefault("inviti_attivi", {})

    code = f"inv_{secrets.token_hex(3)}"
    inviti[code] = {
        "creato_il": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "creato_da": admin_name,
        "usato": False,
        "usato_da": None
    }
    save_config(config)
    write_log(f"INVITO: Generato codice monouso {code} da {admin_name}")
    return f"https://t.me/prezzitrenibot?start={code}"


def handle_search_date(client: TrenitaliaClient, token: str, chat_id: str, config: Dict[str, Any], date_input: str):
    date_normalized = normalize_date(date_input)
    if not date_normalized:
        send_tg_msg(token, chat_id, "❌ <b>Data non valida!</b> Usa il formato <code>GG/MM/AAAA</code> (es. <code>21/12/2026</code>):")
        return

    tr = config.get("treno", {})
    orig_id = tr.get("id_partenza", 830000219)
    dest_id = tr.get("id_arrivo", 830011019)
    orig_name = tr.get("stazione_partenza", "Torino Porta Nuova")
    dest_name = tr.get("stazione_arrivo", "Termoli")

    trains = client.get_day_trains_summary(orig_id, dest_id, date_normalized)
    if not trains:
        send_tg_msg(token, chat_id, f"ℹ️ Nessun treno trovato per il <b>{date_normalized}</b> ({orig_name} ➔ {dest_name}).", get_main_menu_keyboard(config, chat_id))
        return

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

        cb_data = f"sel|{num}|{dep}|{date_normalized}|{cat[:4]}"
        btn_label = f"🎯 Seleziona {cat} {num} ({dep})"
        inline_buttons.append([{"text": btn_label, "callback_data": cb_data}])

    inline_buttons.append([{"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}])
    full_text = "\n".join(text_lines) + "\n\n👉 <i>Tocca il treno desiderato per avviare il monitoraggio:</i>"
    send_tg_msg(token, chat_id, full_text, {"inline_keyboard": inline_buttons})


def handle_telegram_events(
    client: TrenitaliaClient,
    config: Dict[str, Any],
    last_offset: Optional[int]
) -> Optional[int]:
    tg_cfg = config.get("notifiche_telegram", {})
    if not tg_cfg.get("abilitato"):
        return last_offset

    token = os.environ.get("TELEGRAM_BOT_TOKEN") or tg_cfg.get("bot_token", "").strip()
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

            try:
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

                    if not is_user_authorized(sender_id, config):
                        answer_tg_callback(token, cb_id, "Accesso non autorizzato!")
                        send_tg_msg(token, sender_id, "⛔ <b>Accesso Riservato</b>\nRichiedi l'autorizzazione al proprietario del bot.")
                        continue

                    if data_val == "cmd_menu":
                        answer_tg_callback(token, cb_id)
                        send_main_menu(token, sender_id, config)

                    elif data_val == "cmd_admin_menu":
                        answer_tg_callback(token, cb_id)
                        if is_admin(sender_id, config):
                            send_admin_menu(token, sender_id, config)
                        else:
                            send_main_menu(token, sender_id, config)

                    elif data_val == "cmd_status":
                        answer_tg_callback(token, cb_id, "Recupero situazione treno...")
                        train_data = fetch_train_data(client, config)
                        data_v = config.get("treno", {}).get("data_viaggio", "2026-12-21")
                        if train_data:
                            send_tg_msg(token, sender_id, build_telegram_summary(train_data, data_v), get_main_menu_keyboard(config, sender_id))
                        else:
                            send_tg_msg(token, sender_id, "❌ Impossibile recuperare i dati al momento.", get_main_menu_keyboard(config, sender_id))

                    elif data_val == "cmd_routes":
                        answer_tg_callback(token, cb_id)
                        send_routes_menu(token, sender_id, config)

                    elif data_val.startswith("set_route_"):
                        answer_tg_callback(token, cb_id, "Tratta aggiornata!")
                        r_key = data_val.replace("set_route_", "")
                        if r_key in TRATTE_PRESET:
                            route_info = TRATTE_PRESET[r_key]
                            config["treno"]["stazione_partenza"] = route_info["partenza"]
                            config["treno"]["id_partenza"] = route_info["id_partenza"]
                            config["treno"]["stazione_arrivo"] = route_info["arrivo"]
                            config["treno"]["id_arrivo"] = route_info["id_arrivo"]
                            save_config(config)
                            save_state({})

                            txt = (
                                f"✅ <b>Tratta impostata:</b> {route_info['label']}!\n\n"
                                "👉 Tocca <b>🔍 Scegli Giorno & Treno</b> per visualizzare tutti i treni su questa tratta."
                            )
                            send_tg_msg(token, sender_id, txt, get_main_menu_keyboard(config, sender_id))

                    elif data_val == "route_swap":
                        answer_tg_callback(token, cb_id, "Direzione invertita!")
                        tr = config.get("treno", {})
                        p_name, a_name = tr.get("stazione_partenza"), tr.get("stazione_arrivo")
                        p_id, a_id = tr.get("id_partenza"), tr.get("id_arrivo")

                        config["treno"]["stazione_partenza"] = a_name
                        config["treno"]["id_partenza"] = a_id
                        config["treno"]["stazione_arrivo"] = p_name
                        config["treno"]["id_arrivo"] = p_id
                        save_config(config)
                        save_state({})

                        send_tg_msg(
                            token,
                            sender_id,
                            f"🔄 <b>Tratta Invertita:</b> <b>{a_name} ➔ {p_name}</b>\n\nTocca <b>🔍 Scegli Giorno & Treno</b> per aggiornare i treni.",
                            get_main_menu_keyboard(config, sender_id)
                        )

                    elif data_val == "route_custom":
                        answer_tg_callback(token, cb_id)
                        USER_STATES[sender_id] = "WAIT_CUSTOM_ORIGIN"
                        send_tg_msg(
                            token,
                            sender_id,
                            "🗺️ <b>IMPOSTAZIONE TRATTA PERSONALIZZATA</b>\n\n"
                            "📍 <b>Scrivi il nome della stazione di PARTENZA:</b>\n"
                            "(es: <i>Torino, Milano, Roma, Benevento, Termoli, Napoli, Firenze, Bologna, Bari...</i>)"
                        )

                    elif data_val.startswith("set_orig_id_"):
                        answer_tg_callback(token, cb_id)
                        parts = data_val.replace("set_orig_id_", "").split("|", 1)
                        s_id = int(parts[0])
                        s_name = parts[1]
                        USER_TEMP_DATA[sender_id] = {"id_partenza": s_id, "stazione_partenza": s_name}
                        USER_STATES[sender_id] = "WAIT_CUSTOM_DEST"
                        send_tg_msg(
                            token,
                            sender_id,
                            f"✅ Partenza: <b>{s_name}</b>\n\n"
                            "📍 <b>Ora scrivi il nome della stazione di ARRIVO:</b>\n"
                            "(es: <i>Benevento, Termoli, Roma, Torino, Milano, ecc.</i>)"
                        )

                    elif data_val.startswith("set_dest_id_"):
                        answer_tg_callback(token, cb_id)
                        parts = data_val.replace("set_dest_id_", "").split("|", 1)
                        d_id = int(parts[0])
                        d_name = parts[1]

                        temp = USER_TEMP_DATA.get(sender_id, {})
                        orig_name = temp.get("stazione_partenza", config["treno"]["stazione_partenza"])
                        orig_id = temp.get("id_partenza", config["treno"]["id_partenza"])

                        config["treno"]["stazione_partenza"] = orig_name
                        config["treno"]["id_partenza"] = orig_id
                        config["treno"]["stazione_arrivo"] = d_name
                        config["treno"]["id_arrivo"] = d_id
                        save_config(config)
                        save_state({})

                        USER_STATES.pop(sender_id, None)
                        USER_TEMP_DATA.pop(sender_id, None)

                        success_txt = (
                            "🎉 <b>NUOVA TRATTA CONFIGURATA!</b>\n\n"
                            f"📍 <b>{orig_name} ➔ {d_name}</b>\n\n"
                            "👉 Tocca <b>🔍 Scegli Giorno & Treno</b> per vedere le soluzioni disponibili!"
                        )
                        send_tg_msg(token, sender_id, success_txt, get_main_menu_keyboard(config, sender_id))

                    elif data_val == "cmd_create_invite":
                        answer_tg_callback(token, cb_id)
                        if is_admin(sender_id, config):
                            invite_link = create_single_use_invite(config, sender_name)
                            invite_msg = (
                                "🎟️ <b>LINK DI INVITO MONOUSO GENERATO:</b>\n\n"
                                f"👉 <code>{invite_link}</code>\n\n"
                                "• Valido per 1 sola persona (si disattiva dopo l'uso).\n"
                                "<i>Inoltra questo link al tuo amico!</i>"
                            )
                            send_tg_msg(token, sender_id, invite_msg, {"inline_keyboard": [[{"text": "🔙 Torna al Menu Admin", "callback_data": "cmd_admin_menu"}]]})

                    elif data_val == "cmd_toggle_access":
                        answer_tg_callback(token, cb_id, "Modalità accesso modificata!")
                        if is_admin(sender_id, config):
                            sec = config.setdefault("sicurezza", {})
                            current = sec.get("blocco_altri_utenti", False)
                            sec["blocco_altri_utenti"] = not current
                            save_config(config)
                            send_admin_menu(token, sender_id, config, extra_text="🛡️ <b>Modalità di accesso aggiornata!</b>")

                    elif data_val == "cmd_list_users":
                        answer_tg_callback(token, cb_id)
                        if is_admin(sender_id, config):
                            aut_users = config.get("sicurezza", {}).get("utenti_autorizzati", [])
                            admin_id = str(config.get("sicurezza", {}).get("admin_chat_id", ""))
                            u_txt = f"👥 <b>UTENTI AUTORIZZATI ({len(aut_users)}):</b>\n\n"
                            for u_id in aut_users:
                                tag = "👑 Proprietario (Tu)" if str(u_id) == admin_id else "👤 Amico"
                                u_txt += f"• <code>{u_id}</code> - {tag}\n"
                            u_txt += "\n<i>Tutti questi utenti ricevono le notifiche in tempo reale.</i>"
                            send_tg_msg(token, sender_id, u_txt, {"inline_keyboard": [[{"text": "🔙 Torna al Menu Admin", "callback_data": "cmd_admin_menu"}]]})

                    elif data_val.startswith("auth_user_"):
                        answer_tg_callback(token, cb_id, "Utente autorizzato!")
                        if is_admin(sender_id, config):
                            parts = data_val.replace("auth_user_", "").split("|")
                            target_id = parts[0]
                            target_name = parts[1] if len(parts) > 1 else "Utente"
                            sec = config.setdefault("sicurezza", {})
                            aut_list = sec.setdefault("utenti_autorizzati", [])
                            if target_id not in aut_list:
                                aut_list.append(target_id)
                                save_config(config)
                            send_tg_msg(token, sender_id, f"✅ <b>{target_name}</b> (ID: <code>{target_id}</code>) è stato autorizzato con successo!")
                            send_main_menu(token, target_id, config, extra_text=f"🎉 <b>BENVENUTO {target_name}!</b>\nIl proprietario ha approvato il tuo accesso!")

                    elif data_val.startswith("reject_user_"):
                        answer_tg_callback(token, cb_id, "Richiesta rifiutata.")
                        if is_admin(sender_id, config):
                            parts = data_val.replace("reject_user_", "").split("|")
                            target_id = parts[0]
                            target_name = parts[1] if len(parts) > 1 else "Utente"
                            send_tg_msg(token, sender_id, f"⛔ Accesso rifiutato per <b>{target_name}</b>.")
                            send_tg_msg(token, target_id, "⛔ La tua richiesta di accesso a questo bot è stata rifiutata dal proprietario.")

                    elif data_val == "cmd_search_date":
                        answer_tg_callback(token, cb_id)
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
                                    {"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}
                                ]
                            ]
                        }
                        send_tg_msg(
                            token,
                            sender_id,
                            "📅 <b>Scegli la data di viaggio:</b>\n\nTocca una data rapida o <b>scrivi la data</b> in chat (es: <code>21/12/2026</code>):",
                            date_kb
                        )

                    elif data_val.startswith("date_"):
                        chosen_date = data_val.replace("date_", "")
                        answer_tg_callback(token, cb_id, f"Ricerca per il {chosen_date}...")
                        USER_STATES.pop(sender_id, None)
                        handle_search_date(client, token, sender_id, config, chosen_date)

                    elif data_val.startswith("sel|") or data_val.startswith("sel:"):
                        answer_tg_callback(token, cb_id, "Treno impostato!")
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

                        if not re.match(r"^\d{4}-\d{2}-\d{2}$", d_str):
                            d_str = normalize_date(d_str) or "2026-12-21"

                        config["treno"]["numero"] = num
                        config["treno"]["data_viaggio"] = d_str
                        config["treno"]["orario_partenza_previsto"] = dep
                        config["treno"]["categoria"] = "InterCityNotte" if "ICN" in cat or num in ("757", "755") else ("Frecciarossa" if "Frec" in cat else "Treno")
                        save_config(config)
                        save_state({})

                        write_log(f"CONFIG: Impostato treno {num} per il {d_str} ore {dep}")

                        train_data = fetch_train_data(client, config)
                        if train_data:
                            save_state(train_data)
                            full_msg = (
                                f"✅ <b>TRENO SELEZIONATO CON SUCCESSO!</b>\n\n"
                                f"{build_telegram_summary(train_data, d_str)}\n\n"
                                f"🔔 <i>Monitoraggio ATTIVO ogni {config.get('monitoraggio', {}).get('intervallo_minuti', 30)} min!</i>"
                            )
                        else:
                            full_msg = (
                                f"✅ <b>TRENO SELEZIONATO!</b>\n\n"
                                f"• <b>Treno:</b> {config['treno']['categoria']} {num}\n"
                                f"• <b>Data:</b> <code>{d_str}</code> (ore {dep})\n"
                                f"• <b>Monitoraggio:</b> ATTIVO ogni {config.get('monitoraggio', {}).get('intervallo_minuti', 30)} min."
                            )
                        send_tg_msg(token, sender_id, full_msg, get_main_menu_keyboard(config, sender_id))

                    elif data_val == "cmd_frequency":
                        answer_tg_callback(token, cb_id)
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
                        answer_tg_callback(token, cb_id, f"Frequenza: {new_freq} min")
                        config["monitoraggio"]["intervallo_minuti"] = new_freq
                        save_config(config)
                        send_tg_msg(token, sender_id, f"✅ Frequenza aggiornata: controllo ogni <b>{new_freq} minuti</b>!", get_main_menu_keyboard(config, sender_id))

                    elif data_val in ("cmd_pause", "cmd_resume"):
                        new_state = (data_val == "cmd_resume")
                        answer_tg_callback(token, cb_id, "Stato aggiornato!")
                        config["monitoraggio"]["attivo"] = new_state
                        save_config(config)
                        txt = "▶️ Monitoraggio automatico <b>RIPRESO</b>!" if new_state else "⏸️ Monitoraggio automatico <b>SOSPESO</b>!"
                        send_tg_msg(token, sender_id, txt, get_main_menu_keyboard(config, sender_id))

                    elif data_val == "cmd_live":
                        target_num = config.get("treno", {}).get("numero", "757")
                        answer_tg_callback(token, cb_id, f"Interrogo live per {target_num}...")
                        live = client.get_viaggiatreno_live(target_num)
                        if live:
                            vett = live.get("vettore", "Treno")
                            rit = live.get("ritardo", 0)
                            rit_icon = "🟢" if rit <= 0 else ("🟡" if rit <= 15 else "🔴")
                            live_msg = (
                                f"📡 <b>{vett.upper()} {live.get('numero')} IN TEMPO REALE</b>\n\n"
                                f"Origine: {live.get('origine')}\n"
                                f"Destinazione: {live.get('destinazione')}\n"
                                f"{rit_icon} <b>Ritardo:</b> {rit} minuti\n"
                                f"📍 <b>Ultimo Rilevamento:</b> {live.get('stazione_ultimo_rilevamento')} ({live.get('ora_ultimo_rilevamento', '--')})\n"
                            )
                            if live.get("binario_effettivo_partenza"):
                                live_msg += f"🚉 <b>Binario:</b> {live.get('binario_effettivo_partenza')}\n"
                        else:
                            live_msg = f"ℹ️ Nessun dato in tempo reale disponibile per il treno {target_num} in questo momento (parte alle {config.get('treno', {}).get('orario_partenza_previsto', 'orario previsto')})."
                        send_tg_msg(token, sender_id, live_msg, get_main_menu_keyboard(config, sender_id))

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
                text_low = text.lower()

                # GESTIONE INVITI DEEP LINK: /start inv_xxxx
                if text_low.startswith("/start inv_") or (text_low.startswith("/start") and len(text.split()) > 1):
                    token_inv = text.split()[1].strip()
                    sec = config.setdefault("sicurezza", {})
                    inviti = sec.setdefault("inviti_attivi", {})

                    if token_inv in inviti and not inviti[token_inv].get("usato"):
                        inviti[token_inv]["usato"] = True
                        inviti[token_inv]["usato_da"] = f"{sender_name} (ID: {sender_id})"
                        inviti[token_inv]["data_uso"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        aut_list = sec.setdefault("utenti_autorizzati", [])
                        if sender_id not in aut_list:
                            aut_list.append(sender_id)
                        save_config(config)

                        write_log(f"INVITO: {sender_name} autorizzato con {token_inv}")

                        admin_id = sec.get("admin_chat_id")
                        if admin_id and str(admin_id) != sender_id:
                            send_tg_msg(token, admin_id, f"🔔 <b>Nuovo amico connesso con link di invito!</b>\n{sender_name} (ID: <code>{sender_id}</code>)")

                        welcome_msg = (
                            f"🎉 <b>BENVENUTO {sender_name}!</b>\n\n"
                            "Sei stato abilitato con successo tramite link di invito monouso!\n"
                            "Puoi consultare i treni, monitorare posti e prezzi e ricevere notifiche push."
                        )
                        send_main_menu(token, sender_id, config, extra_text=welcome_msg)
                        continue
                    else:
                        send_tg_msg(
                            token,
                            sender_id,
                            "⛔ <b>LINK DI INVITO NON VALIDO O GIÀ UTILIZZATO!</b>\n\n"
                            "Questo link era monouso ed è già stato consumato da un'altra persona.\n"
                            "Chiedi un nuovo link di invito al proprietario del bot."
                        )
                        continue

                # Registrazione automatica del primo admin se non impostato
                admin_id = str(config.get("sicurezza", {}).get("admin_chat_id", "")).strip()
                if not admin_id:
                    admin_id = sender_id
                    config["sicurezza"]["admin_chat_id"] = admin_id
                    if admin_id not in config["sicurezza"].setdefault("utenti_autorizzati", []):
                        config["sicurezza"]["utenti_autorizzati"].append(admin_id)
                    config["notifiche_telegram"]["chat_id"] = admin_id
                    save_config(config)
                    send_admin_menu(token, sender_id, config, extra_text=f"👑 <b>BENVENUTO {sender_name}!</b>\nSei stato registrato come <b>PROPRIETARIO</b> del bot!")
                    continue

                # Controllo accessi per nuovi utenti
                sec = config.setdefault("sicurezza", {})
                blocco_attivo = sec.get("blocco_altri_utenti", False)
                aut_list = sec.setdefault("utenti_autorizzati", [])

                if sender_id not in aut_list and sender_id != admin_id:
                    if not blocco_attivo:
                        aut_list.append(sender_id)
                        save_config(config)
                        write_log(f"ACCESSO LIBERO: Registrato {sender_name} (ID: {sender_id})")
                        if admin_id and str(admin_id) != sender_id:
                            send_tg_msg(token, admin_id, f"👤 <b>Nuovo amico entrato nel bot:</b> {sender_name} (ID: <code>{sender_id}</code>)")
                        send_main_menu(token, sender_id, config, extra_text=f"🎉 <b>BENVENUTO {sender_name}!</b>\nPuoi consultare i treni, verificare posti e prezzi e ricevere notifiche in tempo reale!")
                        continue
                    else:
                        if admin_id and str(admin_id) != sender_id:
                            kb_req = {
                                "inline_keyboard": [
                                    [
                                        {"text": f"✅ Autorizza {sender_name}", "callback_data": f"auth_user_{sender_id}|{sender_name[:15]}"},
                                        {"text": "⛔ Rifiuta", "callback_data": f"reject_user_{sender_id}|{sender_name[:15]}"}
                                    ]
                                ]
                            }
                            send_tg_msg(
                                token,
                                admin_id,
                                f"🔔 <b>RICHIESTA DI ACCESSO AL BOT</b>\n\n"
                                f"👤 <b>Nome:</b> {sender_name}\n"
                                f"🆔 <b>ID Telegram:</b> <code>{sender_id}</code>\n\n"
                                "Tocca qui sotto per abilitarlo:",
                                kb_req
                            )
                        send_tg_msg(
                            token,
                            sender_id,
                            f"👋 <b>Ciao {sender_name}!</b>\n\n"
                            "Questo bot è ad accesso controllato dal proprietario.\n"
                            "📩 <i>Ho inviato una richiesta: riceverai una notifica non appena sarai abilitato!</i>"
                        )
                        continue

                # STATO: Inserimento data
                if USER_STATES.get(sender_id) == "WAITING_DATE":
                    USER_STATES.pop(sender_id, None)
                    handle_search_date(client, token, sender_id, config, text)
                    continue

                # STATO: Scelta stazione partenza personalizzata
                if USER_STATES.get(sender_id) == "WAIT_CUSTOM_ORIGIN":
                    results = client.search_station(text)
                    if not results:
                        send_tg_msg(token, sender_id, f"❌ Nessuna stazione trovata per '{text}'. Riprova a scrivere la stazione di PARTENZA:")
                    elif len(results) == 1 or results[0]["name"].lower() == text.lower():
                        st_id = results[0]["id"]
                        st_name = results[0]["name"]
                        USER_TEMP_DATA[sender_id] = {"id_partenza": st_id, "stazione_partenza": st_name}
                        USER_STATES[sender_id] = "WAIT_CUSTOM_DEST"
                        send_tg_msg(token, sender_id, f"✅ Partenza: <b>{st_name}</b>\n\n📍 <b>Ora scrivi la stazione di ARRIVO:</b>")
                    else:
                        btn_list = []
                        for s in results[:5]:
                            s_name_clean = s['name'][:25].replace('|', ' ')
                            btn_list.append([{"text": s["name"], "callback_data": f"set_orig_id_{s['id']}|{s_name_clean}"}])
                        send_tg_msg(token, sender_id, f"Seleziona la stazione di partenza esatta per '{text}':", {"inline_keyboard": btn_list})
                    continue

                # STATO: Scelta stazione arrivo personalizzata
                if USER_STATES.get(sender_id) == "WAIT_CUSTOM_DEST":
                    results = client.search_station(text)
                    if not results:
                        send_tg_msg(token, sender_id, f"❌ Nessuna stazione trovata per '{text}'. Riprova a scrivere la stazione di ARRIVO:")
                    elif len(results) == 1 or results[0]["name"].lower() == text.lower():
                        d_id = results[0]["id"]
                        d_name = results[0]["name"]
                        temp = USER_TEMP_DATA.get(sender_id, {})
                        orig_name = temp.get("stazione_partenza", config["treno"]["stazione_partenza"])
                        orig_id = temp.get("id_partenza", config["treno"]["id_partenza"])

                        config["treno"]["stazione_partenza"] = orig_name
                        config["treno"]["id_partenza"] = orig_id
                        config["treno"]["stazione_arrivo"] = d_name
                        config["treno"]["id_arrivo"] = d_id
                        save_config(config)
                        save_state({})

                        USER_STATES.pop(sender_id, None)
                        USER_TEMP_DATA.pop(sender_id, None)

                        success_txt = (
                            "🎉 <b>NUOVA TRATTA CONFIGURATA!</b>\n\n"
                            f"📍 <b>{orig_name} ➔ {d_name}</b>\n\n"
                            "👉 Tocca <b>🔍 Scegli Giorno & Treno</b> per vedere le soluzioni disponibili!"
                        )
                        send_tg_msg(token, sender_id, success_txt, get_main_menu_keyboard(config, sender_id))
                    else:
                        btn_list = []
                        for s in results[:5]:
                            s_name_clean = s['name'][:25].replace('|', ' ')
                            btn_list.append([{"text": s["name"], "callback_data": f"set_dest_id_{s['id']}|{s_name_clean}"}])
                        send_tg_msg(token, sender_id, f"Seleziona la stazione di arrivo esatta per '{text}':", {"inline_keyboard": btn_list})
                    continue

                # COMANDI STANDARD
                if text_low in ("/start", "start", "ciao"):
                    send_main_menu(token, sender_id, config)

                elif text_low in ("/menu", "/admin", "/proprietario", "menu", "admin"):
                    if is_admin(sender_id, config):
                        send_admin_menu(token, sender_id, config)
                    else:
                        send_main_menu(token, sender_id, config)

                elif text_low in ("/invito", "/crea_invito", "invito"):
                    if is_admin(sender_id, config):
                        link = create_single_use_invite(config, sender_name)
                        send_tg_msg(
                            token,
                            sender_id,
                            f"🎟️ <b>NUOVO LINK DI INVITO MONOUSO:</b>\n\n👉 <code>{link}</code>\n\n"
                            "<i>Valido per 1 sola persona. Appena l'amico preme 'Avvia', il link si disattiva!</i>"
                        )
                    else:
                        send_tg_msg(token, sender_id, "Solo il proprietario del bot può creare link di invito.")

                elif text_low in ("/utenti", "utenti"):
                    if is_admin(sender_id, config):
                        aut_users = config.get("sicurezza", {}).get("utenti_autorizzati", [])
                        u_txt = f"👥 <b>UTENTI AUTORIZZATI ({len(aut_users)}):</b>\n"
                        for u_id in aut_users:
                            tag = "👑 Proprietario" if str(u_id) == admin_id else "👤 Amico"
                            u_txt += f"• <code>{u_id}</code> ({tag})\n"
                        send_tg_msg(token, sender_id, u_txt)

                elif text_low.startswith("/autorizza") or text_low.startswith("/sblocca"):
                    if is_admin(sender_id, config):
                        parts = text.split()
                        if len(parts) > 1 and parts[1].isdigit():
                            new_id = parts[1].strip()
                            sec = config.setdefault("sicurezza", {})
                            aut_list = sec.setdefault("utenti_autorizzati", [])
                            if new_id not in aut_list:
                                aut_list.append(new_id)
                                save_config(config)
                            send_tg_msg(token, sender_id, f"✅ ID <code>{new_id}</code> autorizzato con successo!")
                            send_main_menu(token, new_id, config, extra_text="🎉 <b>BENVENUTO!</b>\nSei stato abilitato dal proprietario del bot!")
                        else:
                            send_tg_msg(token, sender_id, "ℹ️ Uso: <code>/autorizza ID_TELEGRAM</code>")

                elif text_low in ("/tratta", "tratta"):
                    send_routes_menu(token, sender_id, config)

                elif text_low in ("/stato", "stato", "/controlla", "controlla", "prezzo"):
                    train_data = fetch_train_data(client, config)
                    data_v = config.get("treno", {}).get("data_viaggio", "2026-12-21")
                    if train_data:
                        send_tg_msg(token, sender_id, build_telegram_summary(train_data, data_v), get_main_menu_keyboard(config, sender_id))
                    else:
                        send_tg_msg(token, sender_id, "❌ Impossibile recuperare i dati al momento.", get_main_menu_keyboard(config, sender_id))

                elif text_low.startswith("/cerca"):
                    parts = text.split(maxsplit=1)
                    if len(parts) > 1:
                        handle_search_date(client, token, sender_id, config, parts[1])
                    else:
                        USER_STATES[sender_id] = "WAITING_DATE"
                        send_tg_msg(token, sender_id, "📅 Invia la data nel formato <code>GG/MM/AAAA</code> (es: <code>21/12/2026</code>):")

                elif text_low in ("/pausa", "pausa"):
                    config["monitoraggio"]["attivo"] = False
                    save_config(config)
                    send_tg_msg(token, sender_id, "⏸️ Monitoraggio <b>SOSPESO</b>!", get_main_menu_keyboard(config, sender_id))

                elif text_low in ("/riprendi", "/avvia", "riprendi", "avvia"):
                    config["monitoraggio"]["attivo"] = True
                    save_config(config)
                    send_tg_msg(token, sender_id, "▶️ Monitoraggio <b>RIPRESO</b>!", get_main_menu_keyboard(config, sender_id))

                elif text_low in ("/live", "live", "ritardo"):
                    target_num = config.get("treno", {}).get("numero", "757")
                    live = client.get_viaggiatreno_live(target_num)
                    if live:
                        vett = live.get("vettore", "Treno")
                        rit = live.get("ritardo", 0)
                        rit_icon = "🟢" if rit <= 0 else ("🟡" if rit <= 15 else "🔴")
                        live_msg = (
                            f"📡 <b>{vett.upper()} {live.get('numero')} IN TEMPO REALE</b>\n\n"
                            f"Origine: {live.get('origine')}\n"
                            f"Destinazione: {live.get('destinazione')}\n"
                            f"{rit_icon} <b>Ritardo:</b> {rit} minuti\n"
                            f"📍 <b>Ultimo Rilevamento:</b> {live.get('stazione_ultimo_rilevamento')} ({live.get('ora_ultimo_rilevamento', '--')})\n"
                        )
                        if live.get("binario_effettivo_partenza"):
                            live_msg += f"🚉 <b>Binario:</b> {live.get('binario_effettivo_partenza')}\n"
                    else:
                        live_msg = f"ℹ️ Nessun dato in tempo reale disponibile per il treno {target_num} in questo momento."
                    send_tg_msg(token, sender_id, live_msg, get_main_menu_keyboard(config, sender_id))

                else:
                    date_check = normalize_date(text)
                    if date_check:
                        handle_search_date(client, token, sender_id, config, date_check)
                    else:
                        send_main_menu(token, sender_id, config)

            except Exception as item_err:
                print(f"Errore gestione update: {item_err}")

        return last_offset
    except Exception as e:
        print(f"Errore getUpdates: {e}")
        return last_offset


def main():
    parser = argparse.ArgumentParser(description="Bot Monitor Treni Pro")
    parser.add_argument("--check-now", action="store_true", help="Esegue un solo controllo ed esce")
    parser.add_argument("--interval", type=int, help="Intervallo in minuti")
    args = parser.parse_args()

    config = load_config()
    notifier = Notifier(config)
    client = TrenitaliaClient()

    print_banner(config)

    if args.check_now:
        check_train(client, notifier, config, is_interactive=True)
        return

    telegram_offset = None
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN") or config.get("notifiche_telegram", {}).get("bot_token", "").strip()
    if tg_token:
        try:
            r = requests.get(f"https://api.telegram.org/bot{tg_token}/getUpdates", timeout=5)
            updates = r.json().get("result", [])
            if updates:
                telegram_offset = updates[-1]["update_id"] + 1
        except Exception:
            pass

    intervallo_min = args.interval if args.interval else config.get("monitoraggio", {}).get("intervallo_minuti", 30)

    print(f"\n🚀 BOT AVVIATO CON GESTIONE MULTI-TRATTA ED INVITI!")
    print(f"   • Controllo automatico: ogni {intervallo_min} minuti")
    print(f"   • Ricezione comandi Telegram attiva (apri @prezzitrenibot)")
    print("   Premi [CTRL+C] per arrestare il bot.\n")

    try:
        ciclo = 1
        while True:
            config = load_config()
            notifier = Notifier(config)
            intervallo_min = config.get("monitoraggio", {}).get("intervallo_minuti", 30)
            intervallo_sec = intervallo_min * 60

            print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] --- CONTROLLO #{ciclo} ---")
            check_train(client, notifier, config)

            prossimo = datetime.datetime.now() + datetime.timedelta(seconds=intervallo_sec)
            print(f"⏳ In ascolto su Telegram... Prossimo controllo alle {prossimo.strftime('%H:%M:%S')} (tra {intervallo_min} min)...")

            sleep_start = time.time()
            last_event_check = 0

            while time.time() - sleep_start < intervallo_sec:
                if time.time() - last_event_check >= 1.0:
                    config = load_config()
                    telegram_offset = handle_telegram_events(client, config, telegram_offset)
                    last_event_check = time.time()
                time.sleep(0.2)

            ciclo += 1

    except KeyboardInterrupt:
        print("\n\n🛑 Bot arrestato. Arrivederci!")


if __name__ == "__main__":
    main()
