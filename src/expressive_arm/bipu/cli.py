from __future__ import annotations
import argparse
import getpass
import json
import os
import signal
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path
from .assets import Assets
from .decisions import Jev, Rules
from .engine import Engine
from .backends import ControllerBackend
from .score import validate_score
from .server import Server
from .telegram import TelegramBridge

DEFAULT = Path.home() / ".config" / "bipu" / "config.json"


def read_config(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Config must be an object")
    return data


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(path, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def run(argv=None):
    p = argparse.ArgumentParser(description="Bipu local pet and choreography runtime")
    p.add_argument("--config", type=Path, default=DEFAULT)
    sub = p.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int)
    serve.add_argument("--open", action="store_true")
    serve.add_argument("--provider", choices=["local_rules", "jev"])
    serve.add_argument("--audio", choices=["browser", "system"], default="browser")
    serve.add_argument(
        "--controller-runtime",
        type=Path,
        help="Explicitly attach to an already running controller; otherwise preview only",
    )
    sub.add_parser("check")
    sub.add_parser("stop")
    sub.add_parser("configure")
    validate = sub.add_parser("validate-score")
    validate.add_argument("file", type=Path)
    args = p.parse_args(argv)
    config = read_config(args.config)
    storage = Path(
        config.get("storage", str(args.config.parent / "runtime"))
    ).expanduser()
    if args.command == "configure":
        key = getpass.getpass("TypeSafe/Jev API key (blank keeps existing): ").strip()
        token = getpass.getpass("Telegram bot token (blank keeps existing): ").strip()
        if key:
            config["typesafe_api_key"] = key
        if token:
            config["telegram_token"] = token
        ids = input(
            "Allowed private Telegram chat IDs, comma separated (blank keeps existing): "
        ).strip()
        if ids:
            config["telegram_chat_ids"] = [int(x.strip()) for x in ids.split(",")]
        private_json(args.config, config)
        print("Saved locally. Restart with --provider jev to use Jev.")
        return
    if args.command == "stop":
        session = json.loads((storage / "session.json").read_text())
        req = urllib.request.Request(
            "http://127.0.0.1:" + str(int(session["port"])) + "/api/shutdown",
            b"{}",
            {"Content-Type": "application/json", "X-Bipu-Token": session["token"]},
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            response.read()
        print("Bipu stopped.")
        return
    assets = Assets(
        config.get("sound_root"), config.get("videos"), config.get("sound_manifest")
    )
    if args.command == "check":
        available = []
        for item in assets.sounds:
            try:
                assets.sound_file(item["id"])
                available.append(item["id"])
            except (ValueError, OSError):
                pass
        print(
            json.dumps(
                {
                    "motions": len(assets.motions),
                    "verified_sounds": len(available),
                    "hardware_connected": False,
                },
                indent=2,
            )
        )
        return
    if args.command == "validate-score":
        steps = validate_score(json.loads(args.file.read_text()), assets)
        print("Valid:", len(steps), "steps")
        return
    provider_name = args.provider or config.get("provider", "local_rules")
    if provider_name not in ("local_rules", "jev"):
        raise ValueError("Unknown provider")
    provider = (
        Jev(os.environ.get("TYPESAFE_API_KEY") or config.get("typesafe_api_key"))
        if provider_name == "jev"
        else Rules()
    )
    backend = (
        ControllerBackend(
            args.controller_runtime, assets, config.get("approved_transitions", [])
        )
        if args.controller_runtime
        else None
    )
    engine = Engine(
        assets,
        provider=provider,
        backend=backend,
        storage=storage,
        system_audio=args.audio == "system",
        idle_min=config.get("idle_min", 45),
        idle_max=config.get("idle_max", 90),
        sleep_after=config.get("sleep_after", 240),
    )
    bridge = None
    server = None
    try:
        server = Server(
            (
                "127.0.0.1",
                args.port if args.port is not None else config.get("port", 8765),
            ),
            engine,
        )
        engine.start_worker()
        if config.get("telegram_enabled", False):
            bridge = TelegramBridge(
                engine,
                os.environ.get("TELEGRAM_BOT_TOKEN") or config.get("telegram_token"),
                config.get("telegram_chat_ids", []),
            )
            bridge.start()
        private_json(
            storage / "session.json",
            {"port": server.server_port, "token": server.token, "pid": os.getpid()},
        )

        def shutdown(*_):
            threading.Thread(target=server.shutdown, daemon=True).start()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, shutdown)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, shutdown)
        url = f"http://127.0.0.1:{server.server_port}"
        print("Bipu —", provider_name, "—", engine.backend.kind, flush=True)
        print(
            url + "  |  Ctrl+C / close this terminal to stop. Starts paused.",
            flush=True,
        )
        if args.open:
            webbrowser.open(url)
        server.serve_forever(poll_interval=0.2)
    finally:
        if bridge:
            bridge.close()
        engine.close()
        if server:
            server.server_close()
            try:
                session = json.loads((storage / "session.json").read_text())
                if session.get("pid") == os.getpid():
                    (storage / "session.json").unlink()
            except (OSError, ValueError):
                pass


def main(argv=None):
    try:
        run(argv)
    except (OSError, ValueError, RuntimeError) as error:
        print("Bipu:", error, file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
