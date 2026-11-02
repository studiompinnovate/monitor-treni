"""
Modulo di Notifica per il Bot Trenitalia
Supporta:
- Notifiche Desktop Windows (Toast native)
- Avvisi Sonori (Beep di sistema)
- Notifiche Telegram Multi-Utente (Broadcast a tutti gli utenti autorizzati)
- Webhook Discord
- Log formattati su console
"""

import os
import sys
import subprocess
import requests
import datetime
from typing import Dict, Any

try:
    import winsound
except ImportError:
    winsound = None


class Notifier:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.mon_cfg = config.get("monitoraggio", {})
        self.tg_cfg = config.get("notifiche_telegram", {})
        self.dc_cfg = config.get("notifiche_discord", {})

    def log(self, text: str, prefix: str = "[INFO]"):
        """Stampa un messaggio formattato con timestamp."""
        now = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] {prefix} {text}")

    def send_sound_alert(self):
        """Emette un segnale sonoro su Windows."""
        if self.mon_cfg.get("suono_avviso", True) and winsound:
            try:
                winsound.Beep(1000, 200)
                winsound.Beep(1400, 300)
            except Exception:
                pass

    def send_windows_toast(self, title: str, message: str):
        """Invia una notifica nativa Desktop Toast di Windows tramite PowerShell."""
        if not self.mon_cfg.get("notifiche_windows", True):
            return

        try:
            safe_title = title.replace("'", "''").replace("\n", " ")
            safe_msg = message.replace("'", "''").replace("\n", " ")

            ps_script = f"""
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
            $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
            $textNodes = $template.GetElementsByTagName('text')
            $textNodes.Item(0).AppendChild($template.CreateTextNode('{safe_title}')) > $null
            $textNodes.Item(1).AppendChild($template.CreateTextNode('{safe_msg}')) > $null
            $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Trenitalia Monitor')
            $notification = [Windows.UI.Notifications.ToastNotification]::new($template)
            $notifier.Show($notification)
            """
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
        except Exception as e:
            self.log(f"Impossibile inviare notifica Windows Toast: {e}", "[WARN]")

    def send_telegram(self, message: str) -> bool:
        """Invia un messaggio Telegram a tutti gli utenti autorizzati (Broadcast)."""
        if not self.tg_cfg.get("abilitato", False):
            return False

        token = os.environ.get("TELEGRAM_BOT_TOKEN") or self.tg_cfg.get("bot_token", "").strip()
        if not token or "INSERISCI" in token:
            return False

        # Elenco destinatari: tutti gli utenti autorizzati + chat_id principale
        recipients = set()
        main_chat = str(self.tg_cfg.get("chat_id", "")).strip()
        if main_chat:
            recipients.add(main_chat)

        sec_users = self.config.get("sicurezza", {}).get("utenti_autorizzati", [])
        for u in sec_users:
            u_str = str(u).strip()
            if u_str:
                recipients.add(u_str)

        if not recipients:
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        success = False
        for cid in recipients:
            try:
                r = requests.post(url, json={"chat_id": cid, "text": message, "parse_mode": "HTML"}, timeout=8)
                if r.status_code == 200:
                    success = True
            except Exception:
                pass

        if success:
            self.log(f"Notifica Telegram inviata a {len(recipients)} utente/i autorizzato/i!", "[TELEGRAM]")
        return success

    def send_discord(self, message: str) -> bool:
        """Invia un messaggio a un Webhook Discord."""
        if not self.dc_cfg.get("abilitato", False):
            return False

        webhook_url = self.dc_cfg.get("webhook_url", "").strip()
        if not webhook_url or "INSERISCI" in webhook_url:
            return False

        try:
            r = requests.post(webhook_url, json={"content": message}, timeout=10)
            if r.status_code in (200, 204):
                self.log("Notifica Discord inviata con successo!", "[DISCORD]")
                return True
            else:
                return False
        except Exception as e:
            return False

    def notify(self, title: str, message: str, is_alert: bool = False, full_details_html: str = None):
        """
        Invia notifiche su tutti i canali attivi.
        Se is_alert è True, emette anche avviso acustico.
        """
        self.log(f"{title}: {message}", "[AVVISO]" if is_alert else "[NOTIFICA]")
        self.send_windows_toast(title, message)

        if is_alert:
            self.send_sound_alert()

        tg_text = full_details_html if full_details_html else f"<b>{title}</b>\n\n{message}"
        self.send_telegram(tg_text)
        self.send_discord(f"**{title}**\n{message}")
