"""
Modulo di Notifica per il Bot Trenitalia
Supporta:
- Notifiche Desktop Windows (Toast native)
- Avvisi Sonori (Beep di sistema)
- Notifiche Telegram (Messaggi su smartphone/PC)
- Webhook Discord
- Log formattati su console
"""

import sys
import subprocess
import requests
import datetime
from typing import Dict, Any

# Prova a importare winsound (disponibile nativamente su Windows)
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
                # Emette due beep distinti di avviso
                winsound.Beep(1000, 200)
                winsound.Beep(1400, 300)
            except Exception:
                pass

    def send_windows_toast(self, title: str, message: str):
        """Invia una notifica nativa Desktop Toast di Windows tramite PowerShell."""
        if not self.mon_cfg.get("notifiche_windows", True):
            return

        try:
            # Escape sicuro per PowerShell
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
        """Invia un messaggio Telegram al canale/chat configurato."""
        if not self.tg_cfg.get("abilitato", False):
            return False

        token = self.tg_cfg.get("bot_token", "").strip()
        chat_id = self.tg_cfg.get("chat_id", "").strip()

        if not token or not chat_id or "INSERISCI" in token:
            self.log("Telegram abilitato ma token o chat_id non configurati in config.json", "[WARN]")
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code == 200:
                self.log("Notifica Telegram inviata con successo!", "[TELEGRAM]")
                return True
            else:
                self.log(f"Errore invio Telegram ({r.status_code}): {r.text}", "[ERRORE]")
                return False
        except Exception as e:
            self.log(f"Errore di connessione Telegram: {e}", "[ERRORE]")
            return False

    def send_discord(self, message: str) -> bool:
        """Invia un messaggio a un Webhook Discord."""
        if not self.dc_cfg.get("abilitato", False):
            return False

        webhook_url = self.dc_cfg.get("webhook_url", "").strip()
        if not webhook_url or "INSERISCI" in webhook_url:
            self.log("Discord abilitato ma webhook_url non configurato", "[WARN]")
            return False

        try:
            r = requests.post(webhook_url, json={"content": message}, timeout=10)
            if r.status_code in (200, 204):
                self.log("Notifica Discord inviata con successo!", "[DISCORD]")
                return True
            else:
                self.log(f"Errore Discord ({r.status_code}): {r.text}", "[ERRORE]")
                return False
        except Exception as e:
            self.log(f"Errore di connessione Discord: {e}", "[ERRORE]")
            return False

    def notify(self, title: str, message: str, is_alert: bool = False, full_details_html: str = None):
        """
        Invia notifiche su tutti i canali attivi.
        Se is_alert è True, emette anche avviso acustico.
        """
        # Log in console
        self.log(f"{title}: {message}", "[AVVISO]" if is_alert else "[NOTIFICA]")

        # Windows Toast
        self.send_windows_toast(title, message)

        # Suono
        if is_alert:
            self.send_sound_alert()

        # Telegram
        tg_text = full_details_html if full_details_html else f"<b>{title}</b>\n\n{message}"
        self.send_telegram(tg_text)

        # Discord
        self.send_discord(f"**{title}**\n{message}")
