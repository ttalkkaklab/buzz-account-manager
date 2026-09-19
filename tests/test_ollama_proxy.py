import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('proxy', Path(__file__).resolve().parents[1] / 'scripts/ollama_anthropic_proxy.py')
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class ProxyTests(unittest.TestCase):
    def request(self):
        return {'system': 'Existing instructions', 'tools': [{'name': 'mcp__buzz__shell'}],
                'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': '<buzz-event type="mentions">test</buzz-event>'}]},
                             {'role': 'system', 'content': [{'type': 'text', 'text': 'ACP instructions'}]}]}

    def test_trailing_system_still_gets_delivery_instruction(self):
        original = self.request()
        before = copy.deepcopy(original)
        result = proxy.normalize(original)
        self.assertEqual(original, before)
        self.assertEqual([m['role'] for m in result['messages']], ['user'])
        self.assertEqual([c['text'] for c in result['system']], ['Existing instructions', 'ACP instructions'])
        instruction = result['messages'][-1]['content'][-1]['text']
        self.assertIn('mcp__buzz__shell tool', instruction)
        self.assertIn('--reply-to TRIGGER_EVENT_ID', instruction)
        self.assertNotIn('Bash', instruction)
        self.assertEqual(proxy.normalize(result), result)

    def test_tool_result_does_not_request_duplicate_delivery(self):
        request = self.request()
        request['messages'].insert(1, {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 't'}]})
        request['messages'].insert(2, {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 't', 'content': '<buzz-event type="mentions">'}]})
        result = proxy.normalize(request)
        self.assertEqual(len(result['messages'][-1]['content']), 1)

    def test_plain_prompt_and_missing_shell_are_unchanged(self):
        request = self.request()
        request['messages'] = [{'role': 'user', 'content': 'Reply OK'}]
        self.assertEqual(proxy.normalize(request), request)
        request = self.request()
        request['tools'] = []
        self.assertEqual(len(proxy.normalize(request)['messages'][0]['content']), 1)

    def test_builtin_shell_and_string_content(self):
        request = self.request()
        request['tools'] = [{'name': 'Bash'}]
        request['messages'][0]['content'] = '<buzz-event type="mentions">test</buzz-event>'
        request['messages'][-1]['content'] = 'ACP instructions'
        self.assertIn('Bash tool', proxy.normalize(request)['messages'][0]['content'][-1]['text'])
