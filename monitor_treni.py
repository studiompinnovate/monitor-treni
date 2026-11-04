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

try:
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except Exception:
    ROME_TZ = datetime.timezone(datetime.timedelta(hours=1))

def get_now() -> datetime.datetime:
    return datetime.datetime.now(ROME_TZ)

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
    now_str = get_now().strftime("%Y-%m-%d %H:%M:%S")
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

    now_str = get_now().strftime("%H:%M:%S")
    lines.append(f"\n<i>Aggiornato alle ore {now_str}</i>")
    return "\n".join(lines)


GLOBAL_NEXT_CHECK: Optional[float] = None


def set_next_check(ts: float):
    global GLOBAL_NEXT_CHECK
    GLOBAL_NEXT_CHECK = ts


def get_countdown_info() -> Dict[str, Any]:
    global GLOBAL_NEXT_CHECK
    if not GLOBAL_NEXT_CHECK:
        return {"minuti": 0, "secondi": 0, "orario": "--:--:--", "testo": "Calcolo in corso... ⏳"}
    rem = int(GLOBAL_NEXT_CHECK - time.time())
    next_dt = get_now() + datetime.timedelta(seconds=max(0, rem))
    ora_str = next_dt.strftime("%H:%M:%S")
    if rem <= 0:
        return {"minuti": 0, "secondi": 0, "orario": ora_str, "testo": "Controllo in corso adesso! 🔄"}
    mins = rem // 60
    secs = rem % 60
    return {
        "minuti": mins,
        "secondi": secs,
        "orario": ora_str,
        "testo": f"alle <b>{ora_str}</b> (tra {mins} min e {secs} sec)"
    }


def ensure_user_profile(config: Dict[str, Any], user_id: str, user_name: str = "Utente") -> Dict[str, Any]:
    utenti = config.setdefault("utenti", {})
    s_id = str(user_id).strip()
    if s_id not in utenti:
        utenti[s_id] = {
            "nome": user_name,
            "creato_il": get_now().strftime("%Y-%m-%d %H:%M:%S"),
            "treni": []
        }
    admin_id = str(config.get("sicurezza", {}).get("admin_chat_id", "512549882")).strip()
    if s_id == admin_id and not utenti[s_id].get("treni") and config.get("treno"):
        tr = config.get("treno")
        t_id = f"{tr.get('numero')}_{tr.get('data_viaggio')}"
        utenti[s_id]["treni"].append({
            "id": t_id,
            "numero": str(tr.get("numero", "757")),
            "categoria": tr.get("categoria", "InterCityNotte"),
            "stazione_partenza": tr.get("stazione_partenza", "Torino Porta Nuova"),
            "id_partenza": tr.get("id_partenza", 830000219),
            "stazione_arrivo": tr.get("stazione_arrivo", "Termoli"),
            "id_arrivo": tr.get("id_arrivo", 830011019),
            "data_viaggio": tr.get("data_viaggio", "2026-12-21"),
            "orario_partenza_previsto": tr.get("orario_partenza_previsto", "20:50"),
            "aggiunto_il": get_now().strftime("%Y-%m-%d %H:%M:%S")
        })
    return utenti[s_id]


def get_user_trains(config: Dict[str, Any], user_id: str) -> List[Dict[str, Any]]:
    s_id = str(user_id).strip()
    utenti = config.get("utenti", {})
    if s_id in utenti:
        return utenti[s_id].get("treni", [])
    admin_id = str(config.get("sicurezza", {}).get("admin_chat_id", "512549882")).strip()
    if s_id == admin_id and config.get("treno"):
        tr = config.get("treno")
        return [{
            "id": f"{tr.get('numero')}_{tr.get('data_viaggio')}",
            "numero": str(tr.get("numero", "757")),
            "categoria": tr.get("categoria", "InterCityNotte"),
            "stazione_partenza": tr.get("stazione_partenza", "Torino Porta Nuova"),
            "id_partenza": tr.get("id_partenza", 830000219),
            "stazione_arrivo": tr.get("stazione_arrivo", "Termoli"),
            "id_arrivo": tr.get("id_arrivo", 830011019),
            "data_viaggio": tr.get("data_viaggio", "2026-12-21"),
            "orario_partenza_previsto": tr.get("orario_partenza_previsto", "20:50")
        }]
    return []


def add_user_train(config: Dict[str, Any], user_id: str, train_info: Dict[str, Any], user_name: str = "Utente") -> bool:
    prof = ensure_user_profile(config, user_id, user_name)
    treni = prof.setdefault("treni", [])
    t_id = f"{train_info.get('numero')}_{train_info.get('data_viaggio')}"
    for t in treni:
        if t.get("id") == t_id:
            return False
    train_info["id"] = t_id
    train_info["aggiunto_il"] = get_now().strftime("%Y-%m-%d %H:%M:%S")
    treni.append(train_info)
    save_config(config)
    return True


def remove_user_train(config: Dict[str, Any], user_id: str, train_id: str) -> bool:
    prof = ensure_user_profile(config, user_id)
    treni = prof.get("treni", [])
    new_treni = [t for t in treni if t.get("id") != train_id]
    if len(new_treni) != len(treni):
        prof["treni"] = new_treni
        save_config(config)
        return True
    return False


def fetch_train_data_for(client: TrenitaliaClient, treno_cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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


def fetch_train_data(client: TrenitaliaClient, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return fetch_train_data_for(client, config.get("treno", {}))


def check_train(client: TrenitaliaClient, notifier: Notifier, config: Dict[str, Any], is_interactive: bool = False):
    """
    Controllo multi-utente e multi-treno.
    Ogni utente riceve ESCLUSIVAMENTE gli aggiornamenti dei suoi treni monitorati.
    """
    mon_cfg = config.get("monitoraggio", {})
    if not mon_cfg.get("attivo", True) and not is_interactive:
        notifier.log("Monitoraggio in PAUSA.", "[PAUSA]")
        return

    threshold = mon_cfg.get("avviso_sotto_soglia_posti", 10)
    admin_id = str(config.get("sicurezza", {}).get("admin_chat_id", "512549882")).strip()

    ensure_user_profile(config, admin_id)
    utenti = config.get("utenti", {})

    cd_info = get_countdown_info()
    intervallo_min = mon_cfg.get("intervallo_minuti", 10)
    train_cache: Dict[str, Any] = {}

    for u_id, u_data in list(utenti.items()):
        treni = u_data.get("treni", [])
        if not treni:
            continue

        for tr_cfg in treni:
            t_num = str(tr_cfg.get("numero", "757")).strip()
            d_viaggio = tr_cfg.get("data_viaggio", "2026-12-21")
            cache_key = f"{t_num}_{d_viaggio}_{tr_cfg.get('id_partenza')}_{tr_cfg.get('id_arrivo')}"

            if cache_key in train_cache:
                train_data = train_cache[cache_key]
            else:
                train_data = fetch_train_data_for(client, tr_cfg)
                train_cache[cache_key] = train_data

            if not train_data:
                continue

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

            summary_body = build_telegram_summary(train_data, d_viaggio)
            footer = f"\n⏳ <i>Prossimo controllo automatico tra {intervallo_min} min ({cd_info['orario']})</i>"

            if esaurimento:
                header = (
                    "🚨 <b>ATTENZIONE: POSTI IN ESAURIMENTO (MENO DI 10 RIMASTI)!</b>\n"
                    + "\n".join(esaurimento)
                    + "\n" + "—" * 30 + "\n\n"
                )
                full_message = header + summary_body + footer
                is_alert = True
                write_log(f"ESAURIMENTO (<10) per utente {u_id} su treno {t_num}: {len(esaurimento)} offerte sotto soglia.")
            else:
                full_message = summary_body + footer
                is_alert = False

            # Invia ESCLUSIVAMENTE all'utente proprietario di questo treno
            notifier.send_single_user(u_id, full_message)
            notifier.log(f"Notifica treno {t_num} inviata a utente {u_id}", "[INVIO]")


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
    """Tastiera pulita con gestione treni individuali, offerte e countdown."""
    user_trains = get_user_trains(config, sender_id)
    n_trains = len(user_trains)
    trains_label = f"📋 I Miei Treni ({n_trains})"

    kb = [
        [
            {"text": trains_label, "callback_data": "cmd_my_trains"},
            {"text": "➕ Aggiungi Treno", "callback_data": "cmd_routes"}
        ],
        [
            {"text": "🏷️ Miglior Offerta del Giorno", "callback_data": "cmd_best_deal"},
            {"text": "⏳ Countdown Notifica", "callback_data": "cmd_countdown"}
        ],
        [
            {"text": "⏱️ Frequenza", "callback_data": "cmd_frequency"},
            {"text": "📡 Live & Ritardi", "callback_data": "cmd_live"}
        ],
        [
            {"text": "🔄 Aggiorna Menu", "callback_data": "cmd_menu"}
        ]
    ]
    return {"inline_keyboard": kb}


def send_main_menu(token: str, chat_id: str, config: Dict[str, Any], extra_text: str = ""):
    """Mostra la situazione del profilo individuale e i treni monitorati dall'utente."""
    ensure_user_profile(config, chat_id)
    user_trains = get_user_trains(config, chat_id)
    mon = config.get("monitoraggio", {})
    cd = get_countdown_info()

    msg = ""
    if extra_text:
        msg += f"{extra_text}\n\n"

    msg += (
        "🎛️ <b>MONITOR TRENI PERSONALE</b>\n"
        f"📋 <b>Treni nel tuo monitoraggio:</b> <b>{len(user_trains)}</b>\n\n"
    )
    if user_trains:
        for t in user_trains[:3]:
            msg += f"• 🚆 <b>{t.get('categoria', 'Treno')} {t.get('numero')}</b> (il {t.get('data_viaggio')} ore {t.get('orario_partenza_previsto', '--')}): <i>{t.get('stazione_partenza')} ➔ {t.get('stazione_arrivo')}</i>\n"
        if len(user_trains) > 3:
            msg += f"  <i>...e altri {len(user_trains) - 3} treni</i>\n"
    else:
        msg += "<i>Nessun treno in lista. Tocca ➕ Aggiungi Treno qui sotto!</i>\n"

    msg += (
        f"\n⏳ <b>Prossimo invio automatico:</b>\n👉 {cd['testo']}\n"
        f"⏱️ <b>Frequenza:</b> ogni {mon.get('intervallo_minuti', 10)} min\n\n"
        "<i>Tocca un'opzione qui sotto:</i>"
    )
    send_tg_msg(token, chat_id, msg, get_main_menu_keyboard(config, chat_id))


def send_my_trains_menu(token: str, chat_id: str, config: Dict[str, Any]):
    """Mostra l'elenco dei treni monitorati dal singolo utente con opzioni di dettaglio ed eliminazione."""
    user_trains = get_user_trains(config, chat_id)
    if not user_trains:
        txt = (
            "📋 <b>I MIEI TRENI MONITORATI</b>\n\n"
            "Non stai ancora monitorando nessun treno!\n\n"
            "👉 Tocca <b>➕ Aggiungi Treno</b> per cercare una tratta e aggiungere un treno alla tua lista personale."
        )
        kb = [
            [{"text": "➕ Aggiungi Treno", "callback_data": "cmd_routes"}],
            [{"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}]
        ]
        send_tg_msg(token, chat_id, txt, {"inline_keyboard": kb})
        return

    txt = f"📋 <b>I TUOI TRENI IN MONITORAGGIO ({len(user_trains)})</b>\n\n"
    buttons = []
    for t in user_trains:
        num = t.get("numero")
        cat = t.get("categoria", "Treno")
        data_v = t.get("data_viaggio")
        dep = t.get("orario_partenza_previsto", "--")
        orig = t.get("stazione_partenza", "")
        dest = t.get("stazione_arrivo", "")
        t_id = t.get("id", f"{num}_{data_v}")

        txt += f"• 🚆 <b>{cat} {num}</b> ({data_v} ore {dep})\n  📍 <i>{orig} ➔ {dest}</i>\n\n"
        buttons.append([
            {"text": f"📊 Situazione {num} ({data_v})", "callback_data": f"view_train_{t_id}"},
            {"text": f"🗑️ Rimuovi", "callback_data": f"del_train_{t_id}"}
        ])

    buttons.append([
        {"text": "➕ Aggiungi un altro treno", "callback_data": "cmd_routes"},
        {"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}
    ])
    send_tg_msg(token, chat_id, txt, {"inline_keyboard": buttons})


def send_countdown_menu(token: str, chat_id: str, config: Dict[str, Any]):
    """Mostra all'utente il countdown esatto per la prossima notifica automatica con opzione di controllo immediato."""
    cd = get_countdown_info()
    mon = config.get("monitoraggio", {})
    intervallo_min = mon.get("intervallo_minuti", 10)
    user_trains = get_user_trains(config, chat_id)

    msg = (
        "⏳ <b>COUNTDOWN PROSSIMA NOTIFICA AUTOMATICA</b>\n\n"
        f"• <b>Prossimo invio programmato:</b>\n"
        f"👉 <b>{cd['testo']}</b>\n\n"
        f"• <b>Orario stimato invio:</b> <code>{cd['orario']}</code>\n"
        f"• <b>Tempo rimanente:</b> <b>{cd['minuti']} min e {cd['secondi']} sec</b>\n"
        f"• <b>Frequenza controlli:</b> ogni {intervallo_min} minuti\n\n"
        f"📋 <b>I tuoi treni che riceveranno l'aggiornamento ({len(user_trains)}):</b>\n"
    )
    if user_trains:
        for t in user_trains:
            msg += f"  • 🚆 <b>{t.get('categoria', 'Treno')} {t.get('numero')}</b> ({t.get('data_viaggio')} ore {t.get('orario_partenza_previsto', '--')}): <i>{t.get('stazione_partenza')} ➔ {t.get('stazione_arrivo')}</i>\n"
    else:
        msg += "  <i>Nessun treno salvato nel tuo profilo. Tocca ➕ Aggiungi Treno per iniziare!</i>\n"

    msg += "\n💡 <i>Tocca 🔄 Aggiorna per vedere i secondi scalare, oppure ⚡ Controlla Adesso per forzare un controllo istantaneo!</i>"

    kb = [
        [
            {"text": "🔄 Aggiorna Countdown", "callback_data": "cmd_countdown"},
            {"text": "⚡ Controlla Adesso", "callback_data": "cmd_check_now_user"}
        ],
        [
            {"text": f"📋 I Miei Treni ({len(user_trains)})", "callback_data": "cmd_my_trains"},
            {"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}
        ]
    ]
    send_tg_msg(token, chat_id, msg, {"inline_keyboard": kb})


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
    temp = USER_TEMP_DATA.get(chat_id, {})
    if "stazione_partenza" in temp and "stazione_arrivo" in temp:
        p_name = temp["stazione_partenza"]
        a_name = temp["stazione_arrivo"]
    else:
        u_trains = get_user_trains(config, chat_id)
        if u_trains:
            p_name = u_trains[0].get("stazione_partenza")
            a_name = u_trains[0].get("stazione_arrivo")
        else:
            tr = config.get("treno", {})
            p_name = tr.get("stazione_partenza", "Torino Porta Nuova")
            a_name = tr.get("stazione_arrivo", "Termoli")

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
            {"text": "🔄 Inverti Direzione", "callback_data": "route_swap"}
        ],
        [
            {"text": "🗺️ Scegli Qualsiasi Altra Stazione d'Italia", "callback_data": "route_custom"}
        ],
        [
            {"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}
        ]
    ]
    txt = (
        "➕ <b>AGGIUNGI UN TRENO AL TUO MONITORAGGIO</b>\n\n"
        f"📍 <b>Tratta di partenza:</b> <code>{p_name} ➔ {a_name}</code>\n\n"
        "Scegli una tratta rapida oppure imposta <b>qualsiasi altra città d'Italia</b>:\n"
        "<i>(Ogni utente gestisce i propri treni in modo indipendente!)</i>"
    )
    send_tg_msg(token, chat_id, txt, {"inline_keyboard": kb})


def create_single_use_invite(config: Dict[str, Any], admin_name: str) -> str:
    sec = config.setdefault("sicurezza", {})
    inviti = sec.setdefault("inviti_attivi", {})

    code = f"inv_{secrets.token_hex(3)}"
    inviti[code] = {
        "creato_il": get_now().strftime("%Y-%m-%d %H:%M:%S"),
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

    temp = USER_TEMP_DATA.get(chat_id, {})
    if "id_partenza" in temp and "id_arrivo" in temp:
        orig_id = temp["id_partenza"]
        dest_id = temp["id_arrivo"]
        orig_name = temp.get("stazione_partenza", "Partenza")
        dest_name = temp.get("stazione_arrivo", "Arrivo")
    else:
        u_trains = get_user_trains(config, chat_id)
        if u_trains:
            orig_id = u_trains[0].get("id_partenza", 830000219)
            dest_id = u_trains[0].get("id_arrivo", 830011019)
            orig_name = u_trains[0].get("stazione_partenza", "Torino Porta Nuova")
            dest_name = u_trains[0].get("stazione_arrivo", "Termoli")
        else:
            tr = config.get("treno", {})
            orig_id = tr.get("id_partenza", 830000219)
            dest_id = tr.get("id_arrivo", 830011019)
            orig_name = tr.get("stazione_partenza", "Torino Porta Nuova")
            dest_name = tr.get("stazione_arrivo", "Termoli")

    USER_TEMP_DATA[chat_id] = {
        "id_partenza": orig_id,
        "stazione_partenza": orig_name,
        "id_arrivo": dest_id,
        "stazione_arrivo": dest_name,
        "data_viaggio": date_normalized
    }

    send_tg_msg(token, chat_id, f"🔍 <i>Cerco treni da <b>{orig_name}</b> a <b>{dest_name}</b> per il <b>{date_normalized}</b>...</i>")
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
        is_saleable = t.get("acquistabile", False)
        if is_saleable and t.get("prezzo_minimo"):
            p_tot = f"{t['prezzo_minimo']:.2f} €"
            if not t["diretto"] and t.get("dettaglio_str"):
                price_label = f"da <b>{p_tot}</b> ({t['dettaglio_str']})"
            else:
                price_label = f"da <b>{p_tot}</b>"
            btn_label = f"🎯 Seleziona {cat} {num} ({dep}) - {p_tot}"
        else:
            price_label = "<b>ESAURITO ❌</b>"
            btn_label = f"🎯 {cat} {num} ({dep}) [Esaurito]"

        cambi_str = "Diretto" if t["diretto"] else f"{t['num_cambi']} cambio/i"
        text_lines.append(f"• <b>{dep} ➔ {arr}</b> | <b>{desc}</b> ({cambi_str}) | {price_label}")

        cb_data = f"sel|{num}|{dep}|{date_normalized}|{cat[:4]}"
        inline_buttons.append([{"text": btn_label, "callback_data": cb_data}])

    inline_buttons.append([{"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}])
    full_text = "\n".join(text_lines) + "\n\n👉 <i>Tocca il treno desiderato per aggiungerlo al tuo monitoraggio:</i>"
    send_tg_msg(token, chat_id, full_text, {"inline_keyboard": inline_buttons})


def get_active_route_for_user(config: Dict[str, Any], chat_id: str) -> Dict[str, Any]:
    """Determina la tratta attiva per l'utente (da selezione temporanea, treno monitorato o configurazione)."""
    temp = USER_TEMP_DATA.get(chat_id, {})
    if "id_partenza" in temp and "id_arrivo" in temp:
        return {
            "id_partenza": temp["id_partenza"],
            "stazione_partenza": temp.get("stazione_partenza", "Torino Porta Nuova"),
            "id_arrivo": temp["id_arrivo"],
            "stazione_arrivo": temp.get("stazione_arrivo", "Termoli"),
            "data_viaggio": temp.get("data_viaggio")
        }
    u_trains = get_user_trains(config, chat_id)
    if u_trains:
        return {
            "id_partenza": u_trains[0].get("id_partenza", 830000219),
            "stazione_partenza": u_trains[0].get("stazione_partenza", "Torino Porta Nuova"),
            "id_arrivo": u_trains[0].get("id_arrivo", 830011019),
            "stazione_arrivo": u_trains[0].get("stazione_arrivo", "Termoli"),
            "data_viaggio": u_trains[0].get("data_viaggio", "2026-12-21")
        }
    tr = config.get("treno", {})
    return {
        "id_partenza": tr.get("id_partenza", 830000219),
        "stazione_partenza": tr.get("stazione_partenza", "Torino Porta Nuova"),
        "id_arrivo": tr.get("id_arrivo", 830011019),
        "stazione_arrivo": tr.get("stazione_arrivo", "Termoli"),
        "data_viaggio": tr.get("data_viaggio", "2026-12-21")
    }


def send_best_deal_date_prompt(token: str, chat_id: str, config: Dict[str, Any]):
    """Chiede all'utente la data per cui trovare la miglior offerta economica."""
    route = get_active_route_for_user(config, chat_id)
    p_name = route["stazione_partenza"]
    a_name = route["stazione_arrivo"]
    suggested_date = route.get("data_viaggio", "2026-12-21")

    USER_STATES[chat_id] = "WAITING_BESTDEAL_DATE"
    USER_TEMP_DATA.setdefault(chat_id, {}).update({
        "id_partenza": route["id_partenza"],
        "stazione_partenza": p_name,
        "id_arrivo": route["id_arrivo"],
        "stazione_arrivo": a_name
    })

    buttons = []
    if suggested_date:
        buttons.append([
            {"text": f"🏷️ Cerca per il tuo treno ({suggested_date})", "callback_data": f"bestdeal_{suggested_date}"}
        ])

    buttons.extend([
        [
            {"text": "📅 21/12/2026", "callback_data": "bestdeal_2026-12-21"},
            {"text": "📅 22/12/2026", "callback_data": "bestdeal_2026-12-22"}
        ],
        [
            {"text": "📅 23/12/2026", "callback_data": "bestdeal_2026-12-23"},
            {"text": "📅 28/12/2026", "callback_data": "bestdeal_2026-12-28"}
        ],
        [
            {"text": "📅 06/01/2027", "callback_data": "bestdeal_2027-01-06"},
            {"text": "🚉 Cambia Tratta", "callback_data": "cmd_routes"}
        ],
        [
            {"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}
        ]
    ])

    txt = (
        "🏷️ <b>RICERCA DELLA MIGLIOR OFFERTA DEL GIORNO</b>\n\n"
        f"📍 <b>Tratta:</b> <code>{p_name} ➔ {a_name}</code>\n\n"
        "Analizzo tutti i treni della giornata e ti mostro i <b>prezzi più bassi</b>, "
        "il miglior prezzo assoluto e la soluzione diretta più conveniente!\n\n"
        "👉 <i>Scegli una data rapida o scrivi la data in chat (es: <code>21/12/2026</code>):</i>"
    )
    send_tg_msg(token, chat_id, txt, {"inline_keyboard": buttons})


def handle_find_best_deals(client: TrenitaliaClient, token: str, chat_id: str, config: Dict[str, Any], date_input: str):
    """Scansiona tutti i treni della giornata e invia la classifica delle offerte migliori."""
    date_normalized = normalize_date(date_input)
    if not date_normalized:
        send_tg_msg(token, chat_id, "❌ <b>Data non valida!</b> Usa il formato <code>GG/MM/AAAA</code> (es. <code>21/12/2026</code>):")
        return

    route = get_active_route_for_user(config, chat_id)
    orig_id = route["id_partenza"]
    dest_id = route["id_arrivo"]
    orig_name = route["stazione_partenza"]
    dest_name = route["stazione_arrivo"]

    USER_TEMP_DATA.setdefault(chat_id, {}).update({
        "id_partenza": orig_id,
        "stazione_partenza": orig_name,
        "id_arrivo": dest_id,
        "stazione_arrivo": dest_name,
        "data_viaggio": date_normalized
    })

    send_tg_msg(token, chat_id, f"🔍 <i>Scansione tariffe per <b>{orig_name} ➔ {dest_name}</b> il <b>{date_normalized}</b> in corso...</i>")
    trains = client.get_day_trains_summary(orig_id, dest_id, date_normalized)

    if not trains:
        send_tg_msg(
            token,
            chat_id,
            f"ℹ️ Nessun treno trovato per il <b>{date_normalized}</b> ({orig_name} ➔ {dest_name}).",
            get_main_menu_keyboard(config, chat_id)
        )
        return

    # Filtra RIGOROSAMENTE solo i treni con posti disponibili (stato SALEABLE e prezzo valido)
    with_prices = [
        t for t in trains
        if t.get("stato") == "SALEABLE"
        and t.get("acquistabile", True)
        and t.get("prezzo_minimo") is not None
        and t.get("prezzo_minimo") > 0
    ]
    sold_out_count = sum(1 for t in trains if t.get("stato") == "SOLD_OUT" or not t.get("acquistabile", True))

    if not with_prices:
        txt_sold = (
            f"ℹ️ <b>Nessuna tariffa acquistabile trovata per il {date_normalized}</b>\n"
            f"📍 {orig_name} ➔ {dest_name}\n\n"
            f"Trovati {len(trains)} treni, ma tutti i posti risultano al momento esauriti (SOLD OUT) o non ancora messi in vendita."
        )
        send_tg_msg(token, chat_id, txt_sold, get_main_menu_keyboard(config, chat_id))
        return

    with_prices.sort(key=lambda x: x["prezzo_minimo"])
    best_overall = with_prices[0]
    best_direct = next((t for t in with_prices if t.get("diretto")), None)

    sub_info = f" ({sold_out_count} con posti esauriti esclusi)" if sold_out_count > 0 else ""
    txt_lines = [
        "🏷️ <b>MIGLIORI OFFERTE DEL GIORNO</b>",
        f"📍 <b>Tratta:</b> <code>{orig_name} ➔ {dest_name}</code>",
        f"📅 <b>Data:</b> <code>{date_normalized}</code>",
        f"📊 Analizzate <b>{len(trains)} soluzioni</b>{sub_info}.\n"
    ]

    if best_overall.get("diretto"):
        txt_lines.extend([
            "🥇 <b>MIGLIOR PREZZO ASSOLUTO (DIRETTO):</b>",
            f"💰 <b>{best_overall['prezzo_minimo']:.2f} €</b> — 🚆 <b>{best_overall['descrizione_treni']}</b>",
            f"🕒 Partenza <b>{best_overall['orario_partenza']}</b> ➔ Arrivo <b>{best_overall['orario_arrivo']}</b> ({best_overall['durata']}) | <b>Diretto (senza cambi)</b>\n"
        ])
    else:
        p_tot = f"{best_overall['prezzo_minimo']:.2f} €"
        bd = f" ({best_overall['dettaglio_str']})" if best_overall.get("dettaglio_str") else ""
        txt_lines.extend([
            "🥇 <b>MIGLIOR PREZZO ASSOLUTO:</b>",
            f"💰 <b>{p_tot}</b>{bd} — 🚆 <b>{best_overall['descrizione_treni']}</b>",
            f"🕒 Partenza <b>{best_overall['orario_partenza']}</b> ➔ Arrivo <b>{best_overall['orario_arrivo']}</b> ({best_overall['durata']}) | {best_overall['num_cambi']} cambio/i\n"
        ])
        if best_direct:
            txt_lines.extend([
                "⭐ <b>MIGLIOR TRENO DIRETTO (SENZA CAMBI):</b>",
                f"💰 <b>{best_direct['prezzo_minimo']:.2f} €</b> — 🚆 <b>{best_direct['descrizione_treni']}</b>",
                f"🕒 Partenza <b>{best_direct['orario_partenza']}</b> ➔ Arrivo <b>{best_direct['orario_arrivo']}</b> ({best_direct['durata']}) | <b>Diretto</b>\n"
            ])

    txt_lines.append("📋 <b>TOP OFFERTE PIÙ CONVENIENTI:</b>")
    medals = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    buttons = []

    for idx, t in enumerate(with_prices[:5]):
        med = medals[idx] if idx < len(medals) else "•"
        direct_badge = " [Diretto] ⭐" if t["diretto"] else f" [{t['num_cambi']} c.]"
        price_str = f"{t['prezzo_minimo']:.2f} €"
        detail_note = f" <i>({t['dettaglio_str']})</i>" if not t["diretto"] and t.get("dettaglio_str") else ""
        txt_lines.append(
            f"{med} <b>{price_str}</b>{detail_note} | <b>{t['orario_partenza']} ➔ {t['orario_arrivo']}</b> | {t['descrizione_treni']}{direct_badge}"
        )

        num = t["numero_treno_principale"]
        dep = t["orario_partenza"]
        cat = t["categoria_principale"]
        cb_data = f"sel|{num}|{dep}|{date_normalized}|{cat[:4]}"
        buttons.append([
            {"text": f"🎯 Monitora a {price_str} ({dep} - {cat} {num})", "callback_data": cb_data}
        ])

    txt_lines.append("\n👉 <i>Tocca un treno per aggiungerlo subito al tuo monitoraggio:</i>")
    buttons.append([
        {"text": "📅 Altra Data", "callback_data": "cmd_best_deal"},
        {"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}
    ])

    send_tg_msg(token, chat_id, "\n".join(txt_lines), {"inline_keyboard": buttons})


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

                    elif data_val == "cmd_my_trains":
                        answer_tg_callback(token, cb_id)
                        send_my_trains_menu(token, sender_id, config)

                    elif data_val == "cmd_countdown":
                        answer_tg_callback(token, cb_id)
                        send_countdown_menu(token, sender_id, config)

                    elif data_val == "cmd_best_deal":
                        answer_tg_callback(token, cb_id)
                        send_best_deal_date_prompt(token, sender_id, config)

                    elif data_val.startswith("bestdeal_"):
                        chosen_date = data_val.replace("bestdeal_", "")
                        answer_tg_callback(token, cb_id, "Ricerca migliori offerte...")
                        USER_STATES.pop(sender_id, None)
                        handle_find_best_deals(client, token, sender_id, config, chosen_date)

                    elif data_val == "cmd_check_now_user":
                        answer_tg_callback(token, cb_id, "Controllo in corso...")
                        user_trains = get_user_trains(config, sender_id)
                        if not user_trains:
                            send_tg_msg(token, sender_id, "ℹ️ Non hai ancora nessun treno salvato nel tuo profilo.", get_main_menu_keyboard(config, sender_id))
                        else:
                            for tr_cfg in user_trains:
                                t_data = fetch_train_data_for(client, tr_cfg)
                                d_v = tr_cfg.get("data_viaggio", "2026-12-21")
                                if t_data:
                                    send_tg_msg(token, sender_id, f"⚡ <b>CONTROLLO IMMEDIATO ESEGUITO:</b>\n\n{build_telegram_summary(t_data, d_v)}")
                                else:
                                    send_tg_msg(token, sender_id, f"❌ Dati non disponibili al momento per il treno {tr_cfg.get('numero')} ({d_v}).")
                            send_countdown_menu(token, sender_id, config)

                    elif data_val.startswith("view_train_"):
                        t_id = data_val.replace("view_train_", "")
                        answer_tg_callback(token, cb_id, "Recupero dettagli...")
                        user_trains = get_user_trains(config, sender_id)
                        target_train = next((t for t in user_trains if t.get("id") == t_id), None)
                        if not target_train:
                            send_tg_msg(token, sender_id, "❌ Treno non trovato nella tua lista.", get_main_menu_keyboard(config, sender_id))
                        else:
                            t_data = fetch_train_data_for(client, target_train)
                            d_v = target_train.get("data_viaggio", "2026-12-21")
                            if t_data:
                                kb_v = [
                                    [{"text": "🗑️ Rimuovi questo treno", "callback_data": f"del_train_{t_id}"}],
                                    [{"text": "📋 I Miei Treni", "callback_data": "cmd_my_trains"}, {"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}]
                                ]
                                send_tg_msg(token, sender_id, build_telegram_summary(t_data, d_v), {"inline_keyboard": kb_v})
                            else:
                                send_tg_msg(token, sender_id, f"❌ Dati non disponibili al momento per il treno {target_train.get('numero')}.", get_main_menu_keyboard(config, sender_id))

                    elif data_val.startswith("del_train_"):
                        t_id = data_val.replace("del_train_", "")
                        answer_tg_callback(token, cb_id, "Treno rimosso!")
                        remove_user_train(config, sender_id, t_id)
                        send_tg_msg(token, sender_id, "🗑️ <b>Treno rimosso dal tuo monitoraggio personale!</b>")
                        send_my_trains_menu(token, sender_id, config)

                    elif data_val == "cmd_admin_menu":
                        answer_tg_callback(token, cb_id)
                        if is_admin(sender_id, config):
                            send_admin_menu(token, sender_id, config)
                        else:
                            send_main_menu(token, sender_id, config)

                    elif data_val == "cmd_status":
                        answer_tg_callback(token, cb_id, "Recupero situazione...")
                        user_trains = get_user_trains(config, sender_id)
                        if not user_trains:
                            send_tg_msg(token, sender_id, "ℹ️ Nessun treno nel tuo profilo. Tocca ➕ Aggiungi Treno per iniziare!", get_main_menu_keyboard(config, sender_id))
                        else:
                            for tr_cfg in user_trains:
                                t_data = fetch_train_data_for(client, tr_cfg)
                                d_v = tr_cfg.get("data_viaggio", "2026-12-21")
                                if t_data:
                                    send_tg_msg(token, sender_id, build_telegram_summary(t_data, d_v))
                            send_main_menu(token, sender_id, config)

                    elif data_val == "cmd_routes":
                        answer_tg_callback(token, cb_id)
                        send_routes_menu(token, sender_id, config)

                    elif data_val.startswith("set_route_"):
                        r_key = data_val.replace("set_route_", "")
                        if r_key in TRATTE_PRESET:
                            route_info = TRATTE_PRESET[r_key]
                            USER_TEMP_DATA[sender_id] = {
                                "id_partenza": route_info["id_partenza"],
                                "stazione_partenza": route_info["partenza"],
                                "id_arrivo": route_info["id_arrivo"],
                                "stazione_arrivo": route_info["arrivo"]
                            }
                            answer_tg_callback(token, cb_id, f"Tratta: {route_info['label']}")
                            USER_STATES[sender_id] = "WAITING_DATE"
                            date_kb = {
                                "inline_keyboard": [
                                    [
                                        {"text": "📅 21/12/2026", "callback_data": "date_2026-12-21"},
                                        {"text": "📅 22/12/2026", "callback_data": "date_2026-12-22"}
                                    ],
                                    [
                                        {"text": "📅 23/12/2026", "callback_data": "date_2026-12-23"},
                                        {"text": "📅 28/12/2026", "callback_data": "date_2026-12-28"}
                                    ],
                                    [
                                        {"text": "📅 06/01/2027", "callback_data": "date_2027-01-06"},
                                        {"text": "🔙 Torna alle Tratte", "callback_data": "cmd_routes"}
                                    ]
                                ]
                            }
                            send_tg_msg(
                                token,
                                sender_id,
                                f"✅ <b>Tratta selezionata:</b> <code>{route_info['label']}</code>\n\n"
                                "📅 <b>Ora scegli la data di viaggio:</b>\n"
                                "Tocca una data rapida o scrivi la data in chat (es: <code>21/12/2026</code> o <code>28/12/2026</code>):",
                                date_kb
                            )

                    elif data_val == "route_swap":
                        curr_route = USER_TEMP_DATA.get(sender_id, {})
                        if not curr_route:
                            u_trains = get_user_trains(config, sender_id)
                            if u_trains:
                                curr_route = {
                                    "id_partenza": u_trains[0].get("id_partenza", 830000219),
                                    "stazione_partenza": u_trains[0].get("stazione_partenza", "Torino Porta Nuova"),
                                    "id_arrivo": u_trains[0].get("id_arrivo", 830011019),
                                    "stazione_arrivo": u_trains[0].get("stazione_arrivo", "Termoli")
                                }
                            else:
                                tr = config.get("treno", {})
                                curr_route = {
                                    "id_partenza": tr.get("id_partenza", 830000219),
                                    "stazione_partenza": tr.get("stazione_partenza", "Torino Porta Nuova"),
                                    "id_arrivo": tr.get("id_arrivo", 830011019),
                                    "stazione_arrivo": tr.get("stazione_arrivo", "Termoli")
                                }
                        USER_TEMP_DATA[sender_id] = {
                            "id_partenza": curr_route["id_arrivo"],
                            "stazione_partenza": curr_route["stazione_arrivo"],
                            "id_arrivo": curr_route["id_partenza"],
                            "stazione_arrivo": curr_route["stazione_partenza"]
                        }
                        answer_tg_callback(token, cb_id, "Tratta invertita!")
                        swapped = USER_TEMP_DATA[sender_id]
                        USER_STATES[sender_id] = "WAITING_DATE"
                        date_kb = {
                            "inline_keyboard": [
                                [
                                    {"text": "📅 21/12/2026", "callback_data": "date_2026-12-21"},
                                    {"text": "📅 22/12/2026", "callback_data": "date_2026-12-22"}
                                ],
                                [
                                    {"text": "📅 28/12/2026", "callback_data": "date_2026-12-28"},
                                    {"text": "📅 06/01/2027", "callback_data": "date_2027-01-06"}
                                ],
                                [
                                    {"text": "🔙 Torna alle Tratte", "callback_data": "cmd_routes"}
                                ]
                            ]
                        }
                        send_tg_msg(
                            token,
                            sender_id,
                            f"🔄 <b>Tratta Invertita:</b> <code>{swapped['stazione_partenza']} ➔ {swapped['stazione_arrivo']}</code>\n\n"
                            "📅 <b>Ora scegli la data di viaggio:</b>\n"
                            "Tocca una data rapida o scrivi la data in chat (es: <code>28/12/2026</code>):",
                            date_kb
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
                        temp["id_arrivo"] = d_id
                        temp["stazione_arrivo"] = d_name
                        USER_TEMP_DATA[sender_id] = temp
                        USER_STATES[sender_id] = "WAITING_DATE"

                        date_kb = {
                            "inline_keyboard": [
                                [
                                    {"text": "📅 21/12/2026", "callback_data": "date_2026-12-21"},
                                    {"text": "📅 22/12/2026", "callback_data": "date_2026-12-22"}
                                ],
                                [
                                    {"text": "📅 28/12/2026", "callback_data": "date_2026-12-28"},
                                    {"text": "📅 06/01/2027", "callback_data": "date_2027-01-06"}
                                ],
                                [
                                    {"text": "🔙 Torna alle Tratte", "callback_data": "cmd_routes"}
                                ]
                            ]
                        }
                        send_tg_msg(
                            token,
                            sender_id,
                            f"🎉 <b>Tratta configurata:</b> <code>{temp.get('stazione_partenza')} ➔ {d_name}</code>\n\n"
                            "📅 <b>Ora scegli la data di viaggio:</b>\n"
                            "Tocca una data rapida o scrivi la data in chat (es: <code>21/12/2026</code>):",
                            date_kb
                        )

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
                        answer_tg_callback(token, cb_id, "Aggiunta in corso...")
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

                        temp = USER_TEMP_DATA.get(sender_id, {})
                        orig_name = temp.get("stazione_partenza", "Torino Porta Nuova")
                        orig_id = temp.get("id_partenza", 830000219)
                        dest_name = temp.get("stazione_arrivo", "Termoli")
                        dest_id = temp.get("id_arrivo", 830011019)

                        cat_full = "InterCityNotte" if "ICN" in cat or num in ("757", "755", "756") else ("Frecciarossa" if "Frec" in cat else ("Intercity" if "IC" in cat else "Treno"))

                        new_train = {
                            "numero": str(num),
                            "categoria": cat_full,
                            "stazione_partenza": orig_name,
                            "id_partenza": orig_id,
                            "stazione_arrivo": dest_name,
                            "id_arrivo": dest_id,
                            "data_viaggio": d_str,
                            "orario_partenza_previsto": dep
                        }

                        added = add_user_train(config, sender_id, new_train, sender_name)
                        if is_admin(sender_id, config):
                            config["treno"].update(new_train)
                            save_config(config)

                        write_log(f"CONFIG: Utente {sender_id} ({sender_name}) ha aggiunto treno {num} per il {d_str} ore {dep}")

                        train_data = fetch_train_data_for(client, new_train)
                        user_trains_count = len(get_user_trains(config, sender_id))

                        if added:
                            msg_head = "🎉 <b>TRENO AGGIUNTO AL TUO MONITORAGGIO!</b>\n\n"
                        else:
                            msg_head = "ℹ️ <b>QUESTO TRENO È GIÀ PRESENTE NELLA TUA LISTA!</b>\n\n"

                        msg_head += (
                            f"• 🚆 <b>{cat_full} {num}</b> ({d_str} ore {dep})\n"
                            f"• 📍 <i>{orig_name} ➔ {dest_name}</i>\n"
                            f"• 📋 <b>Treni nel tuo profilo:</b> <b>{user_trains_count}</b>\n\n"
                        )

                        if train_data:
                            full_msg = msg_head + build_telegram_summary(train_data, d_str)
                        else:
                            full_msg = msg_head + f"🔔 <i>Monitoraggio ATTIVO ogni {config.get('monitoraggio', {}).get('intervallo_minuti', 10)} min!</i>"

                        kb_next = {
                            "inline_keyboard": [
                                [
                                    {"text": f"📋 I Miei Treni ({user_trains_count})", "callback_data": "cmd_my_trains"},
                                    {"text": "➕ Aggiungi Altro Treno", "callback_data": "cmd_routes"}
                                ],
                                [
                                    {"text": "⏳ Countdown Notifica", "callback_data": "cmd_countdown"},
                                    {"text": "🔙 Menu Principale", "callback_data": "cmd_menu"}
                                ]
                            ]
                        }
                        send_tg_msg(token, sender_id, full_msg, kb_next)

                    elif data_val == "cmd_frequency":
                        answer_tg_callback(token, cb_id)
                        freq_kb = {
                            "inline_keyboard": [
                                [
                                    {"text": "⏱️ Ogni 10 min", "callback_data": "freq_10"},
                                    {"text": "⏱️ Ogni 15 min", "callback_data": "freq_15"}
                                ],
                                [
                                    {"text": "⏱️ Ogni 30 min (Consigliato)", "callback_data": "freq_30"},
                                    {"text": "⏱️ Ogni 60 min", "callback_data": "freq_60"}
                                ],
                                [
                                    {"text": "🔙 Torna al Menu", "callback_data": "cmd_menu"}
                                ]
                            ]
                        }
                        curr = config.get("monitoraggio", {}).get("intervallo_minuti", 10)
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
                        user_trains = get_user_trains(config, sender_id)
                        targets = [t.get("numero", "757") for t in user_trains] if user_trains else [config.get("treno", {}).get("numero", "757")]
                        answer_tg_callback(token, cb_id, f"Interrogo live per {len(targets)} treno/i...")
                        for target_num in targets:
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
                                    live_msg += f"🚉 <b>Binario Partenza:</b> {live.get('binario_effettivo_partenza')}\n"
                            else:
                                live_msg = f"ℹ️ Nessun dato in tempo reale attivo per il treno {target_num} al momento (il treno non è ancora partito o è previsto per una data futura)."
                            send_tg_msg(token, sender_id, live_msg)
                        send_main_menu(token, sender_id, config)

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
                        inviti[token_inv]["data_uso"] = get_now().strftime("%Y-%m-%d %H:%M:%S")

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

                if USER_STATES.get(sender_id) == "WAITING_BESTDEAL_DATE":
                    USER_STATES.pop(sender_id, None)
                    handle_find_best_deals(client, token, sender_id, config, text)
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

                elif text_low in ("/countdown", "/prossimo", "countdown", "prossimo", "/tempo"):
                    send_countdown_menu(token, sender_id, config)

                elif text_low in ("/treni", "/mytrains", "treni"):
                    send_my_trains_menu(token, sender_id, config)

                elif text_low in ("/tratta", "tratta"):
                    send_routes_menu(token, sender_id, config)

                elif text_low in ("/miglior_prezzo", "/migliore", "/offerta", "/offerte", "/best", "/economico", "miglior offerta", "miglior prezzo", "offerte", "offerta", "migliore"):
                    send_best_deal_date_prompt(token, sender_id, config)

                elif text_low in ("/stato", "stato", "/controlla", "controlla", "prezzo"):
                    user_trains = get_user_trains(config, sender_id)
                    if not user_trains:
                        send_tg_msg(token, sender_id, "ℹ️ Non hai ancora nessun treno salvato.", get_main_menu_keyboard(config, sender_id))
                    else:
                        for tr_cfg in user_trains:
                            t_data = fetch_train_data_for(client, tr_cfg)
                            d_v = tr_cfg.get("data_viaggio", "2026-12-21")
                            if t_data:
                                send_tg_msg(token, sender_id, build_telegram_summary(t_data, d_v))
                            else:
                                send_tg_msg(token, sender_id, f"❌ Impossibile recuperare i dati per il treno {tr_cfg.get('numero')} ({d_v}).")
                        send_main_menu(token, sender_id, config)

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
                    user_trains = get_user_trains(config, sender_id)
                    targets = [t.get("numero", "757") for t in user_trains] if user_trains else [config.get("treno", {}).get("numero", "757")]
                    for target_num in targets:
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
                        send_tg_msg(token, sender_id, live_msg)
                    send_main_menu(token, sender_id, config)

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
            intervallo_min = config.get("monitoraggio", {}).get("intervallo_minuti", 10)
            intervallo_sec = intervallo_min * 60

            print(f"\n[{get_now().strftime('%H:%M:%S')}] --- CONTROLLO #{ciclo} ---")
            check_train(client, notifier, config)

            prossimo = get_now() + datetime.timedelta(seconds=intervallo_sec)
            sleep_start = time.time()
            set_next_check(sleep_start + intervallo_sec)
            print(f"⏳ In ascolto su Telegram... Prossimo controllo alle {prossimo.strftime('%H:%M:%S')} (tra {intervallo_min} min)...")

            last_event_check = 0

            while time.time() - sleep_start < intervallo_sec:
                if time.time() - last_event_check >= 1.0:
                    config = load_config()
                    intervallo_sec = config.get("monitoraggio", {}).get("intervallo_minuti", 10) * 60
                    set_next_check(sleep_start + intervallo_sec)
                    telegram_offset = handle_telegram_events(client, config, telegram_offset)
                    last_event_check = time.time()
                time.sleep(0.2)

            ciclo += 1

    except KeyboardInterrupt:
        print("\n\n🛑 Bot arrestato. Arrivederci!")


if __name__ == "__main__":
    main()
