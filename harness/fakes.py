"""Test doubles. Not used by the harness itself."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def call(_tool, **args):
    return {"name": _tool, "args": args}


class ScriptedModel:
    """Plays back a fixed list of assistant turns.

    Each item is either a string (final text, ends the turn) or a list of
    call(...) dicts (tool calls). When the script runs out it says "ok".
    Records every request so tests can inspect what the model was shown.
    """

    model = "scripted"
    url = "mock://"
    temperature = None

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self._n = 0

    def describe(self):
        return {"model": self.model, "url": self.url}

    def complete(self, messages, tools=None, on_retry=None):
        self.requests.append({"messages": [dict(m) for m in messages], "tools": tools})
        item = self.script.pop(0) if self.script else "ok"
        if isinstance(item, str):
            return {"message": {"role": "assistant", "content": item}, "finish_reason": "stop", "usage": {}}
        calls = []
        for c in item:
            self._n += 1
            calls.append({
                "id": f"c{self._n}",
                "type": "function",
                "function": {"name": c["name"], "arguments": json.dumps(c["args"])},
            })
        return {"message": {"role": "assistant", "content": "", "tool_calls": calls}, "finish_reason": "tool_calls", "usage": {}}


class FakeLlamaServer:
    """A tiny /v1/chat/completions server with llama.cpp-style quirks.

    `responses` is a list of (status, body_dict) returned in order.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                outer.requests.append({"path": self.path, "body": json.loads(self.rfile.read(n))})
                status, body = outer.responses.pop(0) if outer.responses else (500, {"error": "empty"})
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
