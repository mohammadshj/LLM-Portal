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
        notify(event="started", task=task)
        if model == "failure":
            # Delay the HTTP error so a successful sibling visibly streams first.
            with condition:
                condition.wait_for(lambda: task in gates, timeout=45)
            return self.send_error(500)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
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
            deadline = time.monotonic() + 60
            while not released(task) and time.monotonic() < deadline:
                # The mock detects the backend's actual upstream socket close.
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                time.sleep(0.1)
            if not released(task):
                notify(event="timeout", task=task)
                return
            self.event(
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": f"LAST[{task}]"},
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
