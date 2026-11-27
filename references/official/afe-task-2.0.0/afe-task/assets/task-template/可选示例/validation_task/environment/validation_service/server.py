from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from state import locked_state, query

VALUES = json.loads(Path("/service/private_data/values.json").read_text())


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.reply(200, {"ready": True}) if self.path == "/health" else self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/validate":
            return self.reply(404, {"error": "not_found"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                raise ValueError("invalid request size")
            request = json.loads(self.rfile.read(size))
            if not isinstance(request, dict):
                raise ValueError("expected object")
        except (ValueError, UnicodeError):
            return self.reply(400, {"error": "invalid_request"})
        with locked_state() as state:
            status, body = query(state, request.get("candidate_id"), VALUES)
        self.reply(status, body)


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
