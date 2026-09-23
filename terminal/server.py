import json,os
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from .store import Store
from .domain import blockers,recommendations
ROOT=Path(__file__).resolve().parents[1]

def main():
    data=ROOT/'data';data.mkdir(exist_ok=True)
    store=Store(os.environ.get('TERMINAL_DB',str(data/'terminal.sqlite3')))
    class Handler(BaseHTTPRequestHandler):
        def respond(self,value,status=200):
            body=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if self.path=='/api/state':
                state=store.read(); self.respond(dict(state=state,blockers={j['id']:blockers(state,j) for j in state['jobs'] if j['status']=='queued'},recommendations=recommendations(state),events=store.events()))
            elif self.path=='/':
                body=(ROOT/'web/index.html').read_bytes(); self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body)
            else:self.respond({'error':'Not found'},404)
        def do_POST(self):
            if self.path!='/api/commands':return self.respond({'error':'Not found'},404)
            # Local learning server: refuse cross-origin browser mutations.
            if self.headers.get('Origin') not in (None,f'http://{self.headers.get("Host")}'):return self.respond({'error':'Origin rejected'},403)
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<=0 or length>8192:raise ValueError('Invalid body size')
                command=json.loads(self.rfile.read(length))
                if not isinstance(command,dict):raise ValueError('Expected object')
                self.respond(store.apply(command))
            except (ValueError,KeyError) as exc:self.respond({'error':str(exc)},409)
    port=int(os.environ.get('PORT','8790'))
    print(f'Terminal Recovery Lab: http://127.0.0.1:{port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()

if __name__=='__main__':main()
