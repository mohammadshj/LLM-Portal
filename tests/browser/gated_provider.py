"""A controlled, localhost-only Chat Completions fixture, run inside the test backend."""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


condition = threading.Condition()
gates = set()


def released(gate):
    with condition:
        return gate in gates


def notify(**fields):
    with condition:
        print(json.dumps(fields), flush=True)


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def event(self, value):
        data = json.dumps(value) if value != "[DONE]" else value
        self.wfile.write(f"data: {data}\n\n".encode())
        self.wfile.flush()

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self.send_error(404)
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if not request.get("stream"):
            return self.send_error(400, "expected stream=true")
        chat = request["messages"][-1]["content"]
        model = request["model"]
        task = f"{chat}/{model}"
        effort = request.get("reasoning_effort")
        off = request.get("thinking") == {"type": "disabled"}
        notify(event="started", task=task, level="off" if off else effort)
        if model == "failure":
            # Delay the HTTP error so a successful sibling visibly streams first.
            with condition:
                condition.wait_for(lambda: task in gates, timeout=45)
            return self.send_error(500)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            if not off:
                for part in ("TRACE[", task + "]"):
                    self.event({"choices": [{"delta": {"reasoning_content": part}}]})
                if model == "fast":
                    with condition:
                        condition.wait_for(
                            lambda: task + "/answer" in gates, timeout=20
                        )
            self.event(
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": f"FIRST[{task}]"},
                            "finish_reason": None,
                        }
                    ]
                }
            )
            if chat == "مطالعهٔ پاسخ طولانی":
                with condition:
                    condition.wait_for(lambda: task + "/body" in gates, timeout=20)
                text = (
                    "\n\n"
                    + "\n\n".join(f"بند {i}" for i in range(70))
                    + "\n\nبند پایانی\n\n```python\ndef live():"
                )
                self.event({"choices": [{"delta": {"content": text}}]})
            deadline = time.monotonic() + 60
            while not released(task) and time.monotonic() < deadline:
                # The mock detects the backend's actual upstream socket close.
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                time.sleep(0.1)
            if not released(task):
                notify(event="timeout", task=task)
                return
            markdown = " return 1\n```" if chat == "مطالعهٔ پاسخ طولانی" else ""
            if chat == "مقایسه Markdown":
                markdown = (
                    "\n\n## نتیجه\n\n**پررنگ** و *تأکید*\n\n> نقل قول\n\n"
                    "1. مورد اول\n\n- مورد دوم\n\n---\n\n"
                    "| الف | ب |\n|---|---|\n| ۱ | ۲ |\n\n"
                    "```python\ndef hello(): return 1\n```\n\n"
                    "[راهنما](https://example.org) [محلی](file:///example) "
                    "<mark>متن</mark> ![تصویر](https://example.org/image)"
                )
            self.event(
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": (
                                    markdown + f"\n\nLAST[{task}]"
                                    if chat == "مطالعهٔ پاسخ طولانی"
                                    else f"LAST[{task}]" + markdown
                                )
                            },
                            "finish_reason": "stop",
                        }
                    ]
                }
            )
            self.event(
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 7,
                        "completion_tokens": 13,
                        "total_tokens": 20,
                        "completion_tokens_details": {
                            "reasoning_tokens": 0 if off else 6
                        },
                    },
                }
            )
            self.event("[DONE]")
            notify(event="finished", task=task)
        except (BrokenPipeError, ConnectionResetError):
            notify(event="disconnected", task=task)


server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
threading.Thread(target=server.serve_forever, daemon=True).start()
notify(event="ready", port=server.server_port)
for line in sys.stdin:
    with condition:
        gates.add(line.strip())
        condition.notify_all()
server.shutdown()
