import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from test_backend import b


class UsageTests(unittest.TestCase):
    def test_codex_windows_keep_units_and_enforcement(self):
        windows, notes = b.codex_usage({'ordinaryUsageAllowed': False, 'rateLimitsByLimitId': {
            'codex': {'primary': {'usedPercent': 25.5, 'windowDurationMins': 300, 'resetsAt': 1800000000},
                      'secondary': {'usedPercent': 105, 'windowDurationMins': 10080},
                      'credits': {'balance': '12.5'}, 'spendControlReached': True}}})
        self.assertEqual(windows[0]['remaining_percent'], 74.5)
        self.assertIn('5시간', windows[0]['label'])
        self.assertEqual(windows[1]['remaining_percent'], 0)
        self.assertIn('7일', windows[1]['label'])
        self.assertTrue(any('크레딧: 12.5' in n for n in notes))
        self.assertTrue(any('제한' in n for n in notes))

    def test_missing_or_invalid_usage_is_never_full_quota(self):
        self.assertEqual(b.codex_usage({}), ([], []))
        for value in (None, '50', float('nan'), float('inf'), True):
            self.assertIsNone(b.remaining_window('window', value))
        windows, _ = b.claude_usage({'seven_day': {'utilization': 64}, 'five_hour': None,
                                   'extra_usage': {'used_credits': 700}})
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]['remaining_percent'], 36)

    def test_fable_is_selectable(self):
        with tempfile.TemporaryDirectory() as tmp:
            models = b.Manager(tmp).models('claude')
            self.assertIn('fable', [m['id'] for m in models])

    def test_custom_claude_credentials_are_scoped_and_not_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = b.Manager(tmp)
            a = dict(id='work', name='work', home=str(Path(tmp) / 'work'), provider='claude', builtin=False)
            b.write_json(Path(a['home']) / '.credentials.json', {'claudeAiOauth': {'accessToken': 'test-private-value'}})
            response = MagicMock()
            response.__enter__.return_value = io.BytesIO(b'{"five_hour":{"utilization":42}}')
            opener = MagicMock()
            opener.open.return_value = response
            with patch.object(manager, 'account', return_value=a), patch.object(b.urllib.request, 'build_opener', return_value=opener):
                result = manager.usage('work')
            self.assertEqual(result['windows'][0]['remaining_percent'], 58)
            self.assertNotIn('test-private-value', json.dumps(result))
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://api.anthropic.com/api/oauth/usage')
            self.assertEqual(request.get_header('Authorization'), 'Bearer test-private-value')

    def test_usage_failure_redacts_upstream_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = b.Manager(tmp)
            with patch.object(manager, 'account_ready', return_value=True), patch.object(manager, 'resolve_cli', side_effect=ValueError('secret-token')):
                result = manager.usage('default-codex')
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['windows'], [])
            self.assertNotIn('secret-token', json.dumps(result))

    def test_grok_and_logged_out_accounts_do_not_fake_balances(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = b.Manager(tmp)
            with patch.object(manager, 'account_ready', return_value=True):
                result = manager.usage('default-grok')
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['windows'], [])
            with patch.object(manager, 'account_ready', return_value=False):
                self.assertEqual(manager.usage('default-codex')['windows'], [])

    def test_structured_device_code_and_login_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = b.Manager(tmp)
            a = dict(id='test', home=tmp, provider='codex', builtin=False)
            rpc = MagicMock()
            rpc.request.return_value = dict(userCode='ABCD-EFGH', verificationUrl='https://auth.openai.com/codex/device', loginId='one')
            rpc.pending = [dict(method='account/login/completed', params=dict(loginId='one', success=True))]
            factory = MagicMock()
            factory.return_value.__enter__.return_value = rpc
            output = io.StringIO()
            with patch.object(manager, 'account', return_value=a), patch.object(manager, 'resolve_cli', return_value='/test/codex'), patch.object(b, 'CodexRPC', factory), contextlib.redirect_stdout(output):
                manager.codex_login('test')
            event = json.loads(output.getvalue().splitlines()[0].removeprefix('BUZZ_LOGIN:'))
            self.assertEqual(event['code'], 'ABCD-EFGH')
            self.assertNotIn('loginId', event)
            self.assertEqual(factory.call_args.args[1]['CODEX_HOME'], tmp)

    def test_login_cancel_calls_native_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = b.Manager(tmp)
            a = dict(id='test', home=tmp, provider='codex', builtin=False)
            rpc = MagicMock()
            rpc.request.return_value = dict(userCode='ABCD-EFGH', verificationUrl='https://auth.openai.com/codex/device', loginId='one')
            rpc.pending = []
            rpc.receive.side_effect = KeyboardInterrupt()
            factory = MagicMock()
            factory.return_value.__enter__.return_value = rpc
            with patch.object(manager, 'account', return_value=a), patch.object(manager, 'resolve_cli', return_value='/test/codex'), patch.object(b, 'CodexRPC', factory), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(ValueError):
                    manager.codex_login('test')
            rpc.send.assert_called_once_with('account/login/cancel', {'loginId': 'one'}, 999)

    def test_redirects_never_forward_credentials(self):
        self.assertIsNone(b.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))
