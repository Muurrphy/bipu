"""Optional inbound Telegram bridge. No conversational replies or broad chat access."""

import json
import threading
import urllib.request


class TelegramBridge:
    def __init__(self, engine, token, allowed_chats):
        if not token or not allowed_chats:
            raise ValueError("Telegram requires a token AND allowed chat IDs")
        self.engine = engine
        self.token = token
        self.allowed = {int(x) for x in allowed_chats}
        self.offset = 0
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def request(self, payload):
        request = urllib.request.Request(
            "https://api.telegram.org/bot" + self.token + "/getUpdates",
            json.dumps(payload).encode(),
            {"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=18) as response:
            return json.loads(response.read(1024 * 1024))

    def start(self):
        self.thread.start()

    def handle(self, update):
        msg = update.get("message", {})
        chat = msg.get("chat", {})
        # Only explicit private allowlisted chats. Discard stale updates and other content.
        import time

        if (
            chat.get("type") != "private"
            or chat.get("id") not in self.allowed
            or not -5 <= time.time() - msg.get("date", 0) <= 45
        ):
            return
        text = msg.get("text")
        if not isinstance(text, str):
            return
        if text.strip() == "/stop":
            self.engine.stop()
            return
        if text.startswith("/"):
            return
        try:
            self.engine.message(text, "telegram")
        except ValueError:
            pass

    def run(self):
        try:
            first = self.request(
                {"offset": -1, "timeout": 0, "allowed_updates": ["message"]}
            )
            if first.get("ok") is not True:
                raise ValueError()
            for u in first.get("result", []):
                self.offset = max(self.offset, u["update_id"] + 1)
        except Exception:
            self.engine.log(
                "telegram_error",
                detail="Cannot initialize Telegram; check local configuration",
            )
            return
        self.engine.log("telegram_ready", allowed_private_chats=len(self.allowed))
        while not self.stop_event.is_set():
            try:
                response = self.request(
                    {
                        "offset": self.offset,
                        "timeout": 10,
                        "allowed_updates": ["message"],
                    }
                )
                if response.get("ok") is not True:
                    raise ValueError()
                for u in response.get("result", []):
                    self.offset = max(self.offset, u["update_id"] + 1)
                    if not self.stop_event.is_set():
                        self.handle(u)
            except Exception:
                self.engine.log(
                    "telegram_error",
                    detail="Telegram polling failed; credentials are not logged",
                )
                self.stop_event.wait(5)

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=1)
