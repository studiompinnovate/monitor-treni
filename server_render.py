"""
Entry point per il deploy su Render.com (Free Tier)
1. Avvia un leggerissimo server HTTP sulla porta $PORT per superare l'Health Check di Render.
2. Esegue in background il Bot Telegram con pulsanti touch e il monitoraggio Trenitalia ogni 30 minuti 24/7.
"""

import os
import sys
import time
import json
import threading
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# Importa i componenti del nostro bot
from trenitalia_client import TrenitaliaClient
from notifier import Notifier
from monitor_treni import (
    load_config,
    save_config,
    check_train,
    handle_telegram_events,
    print_banner,
    get_now
)

PORT = int(os.environ.get("PORT", 10000))


class RenderHealthHandler(BaseHTTPRequestHandler):
    """Gestisce le richieste HTTP di Render per confermare che l'applicazione è attiva."""
    def do_GET(self):
        if self.path in ("/check", "/check_now", "/controlla"):
            try:
                cfg = load_config()
                client = TrenitaliaClient()
                notifier = Notifier(cfg)
                check_train(client, notifier, cfg, is_interactive=True)
                data = {"status": "SUCCESS", "message": "Controllo eseguito con successo e notifica inviata su Telegram!"}
            except Exception as e:
                data = {"status": "ERROR", "error": str(e)}
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        try:
            cfg = load_config()
            tr = cfg.get("treno", {})
            mon = cfg.get("monitoraggio", {})
            data = {
                "status": "ONLINE",
                "service": "Trenitalia Telegram Bot 24/7",
                "treno": f"{tr.get('categoria', 'ICN')} {tr.get('numero', '757')}",
                "tratta": f"{tr.get('stazione_partenza')} ➔ {tr.get('stazione_arrivo')}",
                "data_viaggio": tr.get("data_viaggio"),
                "frequenza_minuti": mon.get("intervallo_minuti", 30),
                "monitoraggio_attivo": mon.get("attivo", True),
                "server_time": get_now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            data = {"status": "ONLINE", "error": str(e)}

        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        # Evita di riempire i log con i ping continui di healthcheck
        return


def run_http_server():
    """Avvia il server HTTP per Render e il keep-alive automatico."""
    try:
        httpd = HTTPServer(("0.0.0.0", PORT), RenderHealthHandler)
        print(f"🌐 [RENDER] Web server Health Check attivo su porta {PORT}")
        
        # Thread di auto-ping per evitare lo standby di Render
        def self_ping_worker():
            ext_url = os.environ.get("RENDER_EXTERNAL_URL")
            if ext_url:
                print(f"💓 [RENDER] Auto-ping attivato su {ext_url} per mantenere il server sempre sveglio 24/7.")
                import requests
                while True:
                    time.sleep(10 * 60) # ogni 10 minuti
                    try:
                        requests.get(ext_url, timeout=10)
                    except Exception:
                        pass
        
        ping_thread = threading.Thread(target=self_ping_worker, daemon=True)
        ping_thread.start()

        httpd.serve_forever()
    except Exception as e:
        print(f"❌ Errore avvio Web Server: {e}")


def run_bot_daemon():
    """Esegue il ciclo di monitoraggio e ascolto Telegram 24/7."""
    print("🚀 [BOT] Avvio thread di monitoraggio Trenitalia e ascolto Telegram...")
    config = load_config()
    client = TrenitaliaClient()
    notifier = Notifier(config)

    telegram_offset = None
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN") or config.get("notifiche_telegram", {}).get("bot_token", "").strip()

    # Inizializza offset Telegram
    if tg_token:
        try:
            import requests
            r = requests.get(f"https://api.telegram.org/bot{tg_token}/getUpdates", timeout=5)
            updates = r.json().get("result", [])
            if updates:
                telegram_offset = updates[-1]["update_id"] + 1
        except Exception:
            pass

    ciclo = 1
    while True:
        try:
            config = load_config()
            notifier = Notifier(config)
            intervallo_min = config.get("monitoraggio", {}).get("intervallo_minuti", 30)
            intervallo_sec = intervallo_min * 60

            print(f"\n[{get_now().strftime('%H:%M:%S')}] --- CONTROLLO CLOUD #{ciclo} ---")
            check_train(client, notifier, config)

            prossimo = get_now() + datetime.timedelta(seconds=intervallo_sec)
            print(f"⏳ [CLOUD] Prossimo controllo alle {prossimo.strftime('%H:%M:%S')} (tra {intervallo_min} min). In ascolto su Telegram...")

            sleep_start = time.time()
            last_event_check = 0

            # Ascolta i comandi e i pulsanti Telegram ogni secondo
            while time.time() - sleep_start < intervallo_sec:
                if time.time() - last_event_check >= 1.0:
                    config = load_config()
                    intervallo_sec = config.get("monitoraggio", {}).get("intervallo_minuti", 30) * 60
                    telegram_offset = handle_telegram_events(client, config, telegram_offset)
                    last_event_check = time.time()
                time.sleep(0.2)

            ciclo += 1
        except Exception as e:
            print(f"⚠️ Errore nel loop del bot (riprovo tra 10s): {e}")
            time.sleep(10)


def main():
    print("=" * 70)
    print(" ☁️ AVVIO TRENITALIA BOT SU RENDER.COM (24/7)")
    print("=" * 70)
    config = load_config()
    print_banner(config)

    # Avvia il server HTTP in un thread separato (richiesto da Render)
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    # Avvia il monitoraggio nel thread principale
    run_bot_daemon()


if __name__ == "__main__":
    main()
