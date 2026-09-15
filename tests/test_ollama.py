import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_backend import b

class OllamaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = b.Manager(self.temp.name)
        self.pk = 'a' * 64
        b.write_json(self.manager.store, [dict(name='Local test', pubkey=self.pk, runtime='codex', model='old', is_active=True)])
        self.cli = patch.object(self.manager, 'resolve_cli', return_value='/test/bin/claude-agent-acp')
        self.cli.start()
        self.server = patch.object(self.manager, 'ollama_request', side_effect=lambda a,p,payload=None: {'models': [dict(name='local:8b', capabilities=['completion','tools'])]} if p=='/api/tags' else {'capabilities':['completion','tools']})
        self.server.start()
    def tearDown(self):
        self.cli.stop();self.server.stop();self.temp.cleanup()
    def req(self):
        return dict(agent_id=self.pk, provider='ollama', account_id='default-ollama', model='local:8b', effort='', revision=b.revision(self.manager.store.read_bytes()))
    def test_local_model_does_not_need_subscription_login(self):
        self.assertEqual(self.manager.validate(self.req())['provider'], 'ollama')
        with self.assertRaises(ValueError):self.manager.login_plan('default-ollama')
    def test_apply_round_trip_uses_claude_adapter_and_keeps_ollama_selection(self):
        with patch.object(self.manager, 'buzz_running', return_value=False):self.manager.apply(self.req())
        record=b.read_json(self.manager.store)[0]
        self.assertEqual(record['runtime'],'claude')
        self.assertEqual(record['agent_command'],'/test/bin/claude-agent-acp')
        self.assertEqual(record['pubkey'],self.pk)
        self.assertEqual(self.manager.snapshot()['agents'][0]['provider'],'ollama')
        env={'BUZZ_PRIVATE_KEY':'identity','BUZZ_ACP_AGENT_COMMAND':record['agent_command'],'BUZZ_ACP_MODEL':'local:8b',
             'ANTHROPIC_AUTH_TOKEN':'real-secret','ANTHROPIC_CUSTOM_HEADERS':'secret-header','CLAUDE_CODE_OAUTH_TOKEN':'oauth-secret'}
        with patch.dict(os.environ,env,clear=True),patch.object(b.os,'execve') as run:
            self.manager.launch('agent-'+self.pk,[])
        actual=run.call_args.args[2]
        self.assertEqual(actual['ANTHROPIC_AUTH_TOKEN'],'ollama')
        self.assertEqual(actual['ANTHROPIC_API_KEY'],'')
        self.assertEqual(actual['ANTHROPIC_BASE_URL'],'http://127.0.0.1:11434')
        self.assertNotIn('ANTHROPIC_CUSTOM_HEADERS',actual)
        self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN',actual)
        self.assertEqual(actual['ANTHROPIC_DEFAULT_HAIKU_MODEL'],'local:8b')
        self.assertEqual(actual['BUZZ_PRIVATE_KEY'],'identity')
    def test_missing_model_environment_uses_saved_ollama_model(self):
        with patch.object(self.manager, 'buzz_running', return_value=False): self.manager.apply(self.req())
        env={'BUZZ_PRIVATE_KEY':'identity','BUZZ_ACP_AGENT_COMMAND':'/test/bin/claude-agent-acp'}
        with patch.dict(os.environ,env,clear=True),patch.object(b.os,'execve') as run:
            self.manager.launch('agent-'+self.pk,[])
        actual=run.call_args.args[2]
        self.assertEqual(actual['BUZZ_ACP_MODEL'],'local:8b')
        self.assertEqual(actual['BUZZ_ACP_MCP_COMMAND'],'/Applications/Buzz.app/Contents/MacOS/buzz-dev-mcp')
        self.assertEqual(actual['ENABLE_TOOL_SEARCH'],'false')
        self.assertEqual(actual['ANTHROPIC_MODEL'],'local:8b')
        self.assertEqual(actual['ANTHROPIC_DEFAULT_OPUS_MODEL'],'local:8b')
        records=b.read_json(self.manager.store); records[0]['model']=''; b.write_json(self.manager.store,records)
        with patch.dict(os.environ,env,clear=True),patch.object(b.os,'execve') as run:
            with self.assertRaises(ValueError): self.manager.launch('agent-'+self.pk,[])
        run.assert_not_called()

    def test_cloud_embedding_and_non_tool_models_are_not_selectable(self):
        with patch.object(self.manager,'ollama_catalog',return_value={'models':[
            dict(name='cloud:cloud'),dict(name='remote',remote_host='https://ollama.com'),
            dict(name='embed',capabilities=['embedding']),dict(name='text',capabilities=['completion']),
            dict(name='local:8b',capabilities=['completion','tools'])]}):
            self.assertEqual([m['id'] for m in self.manager.ollama_models(self.manager.account('default-ollama'))],['local:8b'])
        with patch.object(self.manager,'ollama_request',return_value={'capabilities':['completion']}):
            with self.assertRaises(ValueError):self.manager.validate(self.req())
    def test_endpoint_and_effort_validation(self):
        for endpoint in ['file:///tmp/test','http://user:password@host:11434','http://host/path','http://host:bad']:
            with self.assertRaises(ValueError):self.manager.ollama_endpoint(endpoint)
        req=self.req();req['effort']='high'
        with self.assertRaises(ValueError):self.manager.validate(req)
    def test_custom_server_has_separate_config_and_no_oauth(self):
        a=self.manager.create_account('LAN','ollama','http://192.168.0.2:11434')
        self.assertEqual(a['endpoint'],'http://192.168.0.2:11434')
        self.assertFalse((Path(a['home'])/'auth.json').exists())
        self.assertEqual(self.manager.auth_env(a,{})['CLAUDE_CONFIG_DIR'],a['home'])
    def test_primary_quota_never_uses_reserve_as_default(self):
        windows,_=b.codex_usage({'rateLimitsByLimitId':{'codex':{'primary':{'usedPercent':100}},'base_model_inference':{'limitName':'gpt-reserve','primary':{'usedPercent':0}}}})
        self.assertEqual([x['remaining_percent'] for x in windows if x['is_primary']],[0])
        windows,_=b.claude_usage({'five_hour':{'utilization':10},'seven_day':{'utilization':20},'seven_day_sonnet':{'utilization':0}})
        self.assertEqual([x['remaining_percent'] for x in windows if x['is_primary']],[90,80])
