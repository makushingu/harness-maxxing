"""Piper worker: runs with the Python of Piper's own environment (state_dir('voice/tts/venv'), see tts.py), as a
separate program, never imported by the server. Keeps the voices loaded between requests.

Protocol (one JSON object per line):
  stdin  {"text": "...", "model": "/path/voice.onnx", "out": "/path/out.wav", "length": 1.0, "speaker": null}
  stdout {"ok": true, "seconds": 2.4} | {"ok": false, "error": "..."}
"""
import json
import sys
import wave

from piper import PiperVoice, SynthesisConfig  # type: ignore[import-not-found]

voices: dict = {}


def main() -> None:
    for line in sys.stdin:
        try:
            req = json.loads(line)
            v = voices.get(req["model"])
            if v is None:
                v = voices[req["model"]] = PiperVoice.load(req["model"])
            spk = req.get("speaker")
            cfg = SynthesisConfig(length_scale=float(req.get("length") or 1.0),
                                  speaker_id=int(spk) if spk is not None else None)
            with wave.open(req["out"], "wb") as w:
                v.synthesize_wav(req["text"], w, syn_config=cfg)
            with wave.open(req["out"], "rb") as r:
                seconds = r.getnframes() / float(r.getframerate() or 1)
            out = {"ok": True, "seconds": round(seconds, 2)}
        except Exception as e:  # one bad request must not stop the worker
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
