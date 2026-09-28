"""Only the subprocess boundary is faked; NavigationTests executes AppModel.create."""
import json
import os
from pathlib import Path
import sys

home = Path(os.environ['HOME'])
state = home / 'fixture-account.json'
action = sys.argv[1]
if action == 'create':
    req = json.load(sys.stdin)
    account = dict(id='created-server', name=req['name'], provider=req['provider'],
                   endpoint=req['endpoint'], home=str(home / 'server'),
                   builtin=False, ready=True, models=[])
    state.write_text(json.dumps(account))
    result = dict(id=account['id'])
elif action == 'status':
    result = dict(revision='fixture', accounts=[json.loads(state.read_text())] if state.exists() else [],
                  agents=[dict(id=i, name=i, provider='codex', model='', effort='medium', account_id='')
                          for i in ['first-agent', 'selected-agent']], cli_available={})
elif action == 'usage':
    req = json.load(sys.stdin)
    result = dict(account_id=req['account_id'], windows=[], notes=[], checked_at='',
                  status='ok', message='')
elif action == 'reorder':
    req = json.load(sys.stdin)
    (home / 'fixture-reorder.json').write_text(json.dumps(req['account_ids']))
    result = dict(message='계정 순서를 저장했습니다.')
else:
    raise RuntimeError('Unexpected fixture action: ' + action)
print(json.dumps(result))
