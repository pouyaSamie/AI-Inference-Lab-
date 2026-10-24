import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

p = argparse.ArgumentParser()
p.add_argument("--port", type=int)
a = p.parse_args()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, value):
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.reply({"n_ctx": 4096})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/apply-template":
            self.reply({"prompt": "".join(m["content"] for m in body["messages"])})
        elif self.path == "/tokenize":
            self.reply({"tokens": list(range(len(body["content"])))})
        elif self.path.endswith("count_tokens"):
            self.reply({"input_tokens": sum(len(m["content"]) for m in body["messages"])})
        else:
            self.reply({"choices": [{"message": {"content": "offline fixture reply"}}]})


ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
