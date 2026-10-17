#!/usr/bin/env python3
"""Real Codex persona/memory checks using only fictional facts and a temporary DB."""
import hashlib
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self, database):
        self.events = queue.Queue()
        self.sequence = 0
        self.child = subprocess.Popen(["node", "scripts/desktop_codex_bridge.mjs"], cwd=ROOT,
            env={**os.environ, "HYPRCHAN_MEMORY_PATH": str(database)},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        def read():
            for line in self.child.stdout:
                self.events.put(json.loads(line))
            self.events.put({"type": "error", "message": "Bridge exited"})
        threading.Thread(target=read, daemon=True).start()
        self.wait("ready", timeout=60)

    def wait(self, kind, identity=None, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self.events.get(timeout=max(.01, deadline - time.monotonic()))
            if event["type"] == "error":
                raise RuntimeError(event["message"])
            if event["type"] == kind and (identity is None or event.get("id") == identity):
                return event
        raise TimeoutError(kind)

    def send(self, command):
        self.child.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
        self.child.stdin.flush()

    def chat(self, text):
        self.sequence += 1
        self.send({"type": "chat", "id": self.sequence, "text": text, "vision": {"enabled": False}})
        result = self.wait("done", self.sequence)
        assert result["status"] == "completed", result
        return {"input": text, **result}

    def close(self):
        if self.child.poll() is None:
            self.send({"type": "quit"})
            try:
                self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.terminate()
                self.child.wait(timeout=3)


def main():
    rows = []
    passed = False
    client = None
    with tempfile.TemporaryDirectory(prefix="hyprchan-memory-eval-") as directory:
        database = Path(directory) / "memory.sqlite3"
        def facts():
            with sqlite3.connect(database) as connection:
                connection.row_factory = sqlite3.Row
                return [dict(row) for row in connection.execute("SELECT key,fact,basis,confidence FROM user_facts")]
        try:
            client = Client(database)
            rows.append({"case": "greeting", **client.chat("Привет!")})
            assert rows[-1]["toolCalls"] == 0
            rows.append({"case": "automatic_learning", **client.chat("Я обычно пью жасминовый чай, кофе не люблю.")})
            assert rows[-1]["toolCalls"] > 0 and facts(), "No real memory write"
            rows.append({"case": "casual_voice", **client.chat("камера опять сломалась, дада дичь какая-то")})
            initial = facts()
            client.close()
            client = Client(database)
            rows.append({"case": "recall_after_restart", **client.chat("Какой напиток я люблю?")})
            assert "чай" in rows[-1]["text"].lower()
            rows.append({"case": "correction", **client.chat("Теперь мой любимый напиток какао вместо жасминового чая. Исправь старую заметку.")})
            corrected = facts()
            assert any("какао" in row["fact"].lower() for row in corrected)
            rows.append({"case": "forget", **client.chat("Забудь все мои предпочтения о напитках, включая чай, кофе и какао.")})
            assert not facts(), "Forgotten beverage facts remain"
            client.close()
            client = Client(database)
            rows.append({"case": "forgotten_after_restart", **client.chat("Ты помнишь мой любимый напиток?")})
            assert not any(word in rows[-1]["text"].lower() for word in ["жасмин", "какао"])
            client.send({"type": "memory_mode", "active": False})
            rows.append({"case": "memory_off", **client.chat("Мой любимый цвет пурпурный.")})
            assert not facts() and rows[-1]["toolCalls"] == 0
            for text in ["hi", "привет", "hi"]:
                rows.append({"case": "warm_greeting", **client.chat(text)})
                assert rows[-1]["toolCalls"] == 0
            passed = True
            print(json.dumps({"passed": passed, "initialFacts": initial, "correctedFacts": corrected,
                              "rows": rows}, ensure_ascii=False, indent=2))
        finally:
            if client:
                client.close()
            output = Path(sys.argv[1])
            output.write_text(json.dumps({"syntheticFactsOnly": True, "passed": passed,
                "promptSha256": hashlib.sha256((ROOT / "benchmarks/codex-rp/persona.txt").read_bytes()).hexdigest(),
                "rows": rows}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
