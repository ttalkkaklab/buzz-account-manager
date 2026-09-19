#!/usr/bin/env python3
"""Local compatibility adapter for Claude ACP's system-role messages."""
import http.server
import json
import urllib.error
import urllib.request

UPSTREAM = 'http://127.0.0.1:11435'

def normalize(body):
    # ACP appends system messages after the user turn. Normalize those first.
    messages = body.get('messages', [])
    extra = [m for m in messages if m.get('role') == 'system']
    if extra:
        system = body.get('system') or []
        system = [{'type': 'text', 'text': system}] if isinstance(system, str) else list(system)
        for message in extra:
            content = message.get('content', [])
            system.extend([{'type': 'text', 'text': content}] if isinstance(content, str) else content)
        messages = [m for m in messages if m.get('role') != 'system']
        body = dict(body, system=system, messages=messages)

    tools = {tool.get('name') for tool in body.get('tools', [])}
    shell = next((name for name in ('mcp__buzz__shell', 'Bash') if name in tools), None)
    if not shell or not messages or messages[-1].get('role') != 'user':
        return body
    content = messages[-1].get('content', [])
    blocks = [{'type': 'text', 'text': content}] if isinstance(content, str) else list(content)
    # A tool result is a continuation, not a new delivery request.
    if any(c.get('type') == 'tool_result' for c in blocks):
        return body
    text = '\n'.join(c.get('text', '') for c in blocks if c.get('type') == 'text')
    marker = 'Buzz delivery requirement:'
    if '<buzz-event ' not in text or marker in text:
        return body
    instruction = (f'{marker} Your final text is private and will NOT appear in the channel. '
        f'For a reply to this event, use the {shell} tool with its command argument to run '
        '/Applications/Buzz.app/Contents/MacOS/buzz messages send '
        '--channel CHANNEL_UUID --reply-to TRIGGER_EVENT_ID --content "your reply", '
        'using the channel and triggering event ID from the buzz-event. '
        'Execute the tool and check accepted=true before claiming delivery. '
        'Do not merely print the command or end with an unsent reply. '
        'Send once; if delivery fails, report the error honestly.')
    blocks.append({'type': 'text', 'text': instruction})
    return dict(body, messages=messages[:-1] + [dict(messages[-1], content=blocks)])

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
