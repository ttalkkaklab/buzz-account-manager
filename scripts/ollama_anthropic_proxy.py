#!/usr/bin/env python3
"""Local compatibility adapter for Claude ACP's system-role messages."""
import http.server
import json
import urllib.error
import urllib.request

UPSTREAM = 'http://127.0.0.1:11435'

def normalize(body):
    extra = [m for m in body.get('messages', []) if m.get('role') == 'system']
    if not extra:
        return body
    system = body.get('system') or []
    if isinstance(system, str):
        system = [{'type': 'text', 'text': system}]
    else:
        system = list(system)
    for message in extra:
        content = message.get('content', [])
        system.extend([{'type': 'text', 'text': content}] if isinstance(content, str) else content)
    return dict(body, system=system, messages=[m for m in body['messages'] if m.get('role') != 'system'])

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def handle_request(self):
        try:
            size = int(self.headers.get('Content-Length', 0))
            if size < 0 or size > 64 * 1024 * 1024:
                self.send_error(413)
                return
            data = self.rfile.read(size) if self.command == 'POST' else None
            if data and self.path.split('?', 1)[0] == '/v1/messages':
                data = json.dumps(normalize(json.loads(data))).encode()
            headers = {key: value for key, value in self.headers.items()
                       if key.lower() in ('content-type', 'anthropic-version', 'anthropic-beta', 'accept')}
            request = urllib.request.Request(UPSTREAM + self.path, data=data, headers=headers, method=self.command)
            try:
                response = urllib.request.urlopen(request, timeout=600)
            except urllib.error.HTTPError as error:
                response = error
            self.send_response(response.status)
            self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
            self.send_header('Connection', 'close')
            self.end_headers()
            with response:
                while True:
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, TypeError, KeyError):
            self.send_error(400, 'Invalid request')
        except (OSError, urllib.error.URLError):
            self.send_error(502, 'Ollama tunnel unavailable')

    do_GET = handle_request
    do_POST = handle_request

if __name__ == '__main__':
    http.server.ThreadingHTTPServer(('127.0.0.1', 11436), Handler).serve_forever()
