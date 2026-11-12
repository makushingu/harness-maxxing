"""`maxxing voice status|set|download|transcribe` - voice messages (speech-to-text) from a shell."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="v_cmd", required=True)
    s = sub.add_parser("status", help="engine, model and readiness")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s = sub.add_parser("set", help="change the settings")
    s.add_argument("--engine", choices=["off", "local", "groq", "openai"])
    s.add_argument("--model", choices=["tiny", "base", "small", "medium"])
    s.add_argument("--language", help="auto or an ISO code (en, fr…)")
    s = sub.add_parser("download", help="download a local model (default: the configured one)")
    s.add_argument("model", nargs="?")
    s = sub.add_parser("transcribe", help="transcribe an audio file with the configured engine")
    s.add_argument("file")


def _handler(a) -> int:
    from . import voice
    try:
        if a.v_cmd == "status":
            st = voice.status()
            if a.json:
                print(json.dumps(st, indent=2))
                return 0
            s = st["settings"]
            print(f"engine   : {s['engine']}   ready: {'yes' if st['ready'] else 'no (' + str(st['reason']) + ')'}")
            print(f"model    : {s['model']} (recommended {st['local']['recommended']})   language: {s['language']}")
            print(f"local    : faster-whisper {'installed' if st['local']['installed'] else 'not installed'}; models "
                  + (", ".join(m["id"] for m in st["local"]["models"] if m["present"]) or "none"))
            print("keys     : " + ", ".join(f"{voice.KEY_NAMES[k]}={'set' if v else 'missing'}" for k, v in st["keys"].items()))
            return 0
        if a.v_cmd == "set":
            s = voice.update_settings(engine=a.engine, model=a.model, language=a.language)
            print(json.dumps(s))
            return 0
        if a.v_cmd == "download":
            name = a.model or voice.settings()["model"]
            print(f"Downloading {name} (~{voice.MODEL_SIZE_MB.get(name, '?')} MB)…", flush=True)
            try:
                print(voice.download_model(name))
            except Exception as e:  # noqa: BLE001 - network, disk or pin errors end as a message, not a traceback
                if isinstance(e, voice.VoiceError):
                    raise
                print(f"error: model {name} could not be downloaded: {e}", file=sys.stderr)
                return 1
            return 0
        out = voice.transcribe_file(Path(a.file))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    except voice.VoiceError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return 1


cli.register("voice", "voice messages (status, set, download, transcribe)", _configure, _handler)
