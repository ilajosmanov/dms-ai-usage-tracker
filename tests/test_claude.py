"""Native protocol and collector integration, using an isolated executable/profile."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from collector import claude
from collector.credentials import discover
from collector.main import collect
from collector.providers import UsageError


FAKE = r'''
import json, os, sys, time
from pathlib import Path
profile = Path(os.environ['CLAUDE_CONFIG_DIR'])
assert '--safe-mode' in sys.argv and '--no-session-persistence' in sys.argv
assert sys.argv[sys.argv.index('--tools')+1] == ''
assert not any(k.startswith('ANTHROPIC_') for k in os.environ)
assert 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC' not in os.environ
assert all(os.environ.get(k) == '1' for k in ('DISABLE_TELEMETRY', 'DISABLE_ERROR_REPORTING', 'DISABLE_AUTOUPDATER'))
mode = (profile / 'mode').read_text()
with (profile / 'calls').open('a') as stream: stream.write('call\n')
def emit(rid, data=None, kind='success'):
 print(json.dumps({'type':'control_response','response':{'subtype':kind,'request_id':rid,'response':data}}), flush=True)
for line in sys.stdin:
 frame = json.loads(line)
 assert frame['type'] == 'control_request'
 request = frame['request']
 if request['subtype'] == 'initialize':
  emit('wrong-request', {'rate_limits_available': False})
  emit(frame['request_id'], {})
  continue
 assert request == {'subtype':'get_usage','skip_behaviors':True}
 if mode == 'timeout':
  (profile / 'pid').write_text(str(os.getpid()))
  time.sleep(30)
 if mode == 'slow':
  (profile / 'started').write_text('yes')
  time.sleep(.4)
 if mode == 'flood':
  sys.stdout.write('x' * 100000); sys.stdout.flush(); time.sleep(30)
 if mode == 'error':
  emit(frame['request_id'], {'secret':'NEVER-PUBLISH-THIS'}, 'error'); continue
 state = json.loads((profile / '.claude.json').read_text())
 limits = {'limits': [
  {'kind':'session','percent':12,'resets_at':None},
  {'kind':'weekly_all','percent':76,'resets_at':None},
  {'kind':'weekly_scoped','percent':97,'resets_at':None,'scope':{'model':{'display_name':'Fable'}}}
 ]}
 if mode in ('success', 'slow', 'switch', 'badshape', 'null'):
  if mode == 'switch': state['oauthAccount']['accountUuid'] = 'other-account'
  state['cachedUsageUtilization'] = {'accountUuid':state['oauthAccount']['accountUuid'],'fetchedAtMs':time.time()*1000,'utilization':limits}
  (profile / '.claude.json').write_text(json.dumps(state))
 (profile / '.credentials.json').write_text(json.dumps({'claudeAiOauth':{'accessToken':'renewed-private-token','expiresAt':(time.time()+3600)*1000}}))
 if mode == 'badshape': limits = {'five_hour': {'utilization':'invalid'}}
 if mode == 'null': limits = None
 emit(frame['request_id'], {'rate_limits_available':True,'rate_limits':limits,'session':{'total_cost_usd':0,'model_usage':{}}})
'''


class ClaudeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.profile = self.home / 'profile with spaces'
        self.profile.mkdir()
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        executable = self.bin / 'claude'
        executable.write_text('#!' + sys.executable + '\n' + FAKE)
        executable.chmod(0o700)
        self.config = {'claudeAuthFile': str(self.profile / '.credentials.json')}
        self.cache = self.home / 'cache/usage.json'
        environment = patch.dict(os.environ, {'PATH': str(self.bin), 'ANTHROPIC_API_KEY':'wrong-login',
                                             'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1'}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.write_state(age=3600)
        self.mode('success')

    def write_state(self, age=0, account='account-one', cache_account=None):
        (self.profile / '.credentials.json').write_text(json.dumps({'claudeAiOauth':{
            'accessToken':'expired-private-token','expiresAt':(time.time()-3600)*1000}}))
        (self.profile / '.claude.json').write_text(json.dumps({
            'oauthAccount':{'accountUuid':account,'organizationUuid':'org-one'},
            'cachedUsageUtilization':{'accountUuid':cache_account or account,
                'fetchedAtMs':(time.time()-age)*1000,
                'utilization':{'five_hour':{'utilization':40}}}}))

    def mode(self, name):
        (self.profile / 'mode').write_text(name)

    def credential(self):
        return next(iter(discover(self.config, self.home).values()))[0]

    def collect(self, **kwargs):
        result = collect(self.config, self.cache, home=self.home, **kwargs)
        return next(a for a in result['accounts'] if a['provider']=='claude')

    def test_expired_login_recovers_through_native_protocol_and_stays_cached(self):
        with patch('collector.main.fetch', side_effect=AssertionError('Claude must not use direct HTTP')):
            account = self.collect()
            self.assertEqual(account['status'], 'ok')
            self.assertEqual([w['used'] for w in account['windows']], [12,76,97])
            self.assertEqual(account['origin'], 'Claude Code')
            self.assertLess(time.time()-account['updatedAt'], 5)
            before = self.cache.read_bytes()
            again = self.collect()
            self.assertEqual(account, again)
            self.assertEqual(self.cache.read_bytes(), before)
        self.assertEqual((self.profile/'calls').read_text().count('call'), 1)
        self.assertNotIn('private-token', json.dumps(account))
        self.assertNotIn('account-one', self.cache.read_text())

    def test_unchanged_old_capture_is_not_relabelled_fresh(self):
        self.mode('stale')
        account = self.collect()
        self.assertEqual(account['status'], 'stale')
        self.assertGreater(time.time()-account['updatedAt'], 3590)
        self.assertIn('could not verify fresh', account['message'])
        self.collect()
        self.assertEqual((self.profile/'calls').read_text().count('call'), 1)

    def test_fresh_cache_avoids_process_even_before_first_network_check(self):
        self.write_state(age=30)
        self.assertEqual(self.collect()['status'], 'ok')
        self.assertFalse((self.profile/'calls').exists())

    def test_thirty_minute_interval_reuses_twenty_minute_capture(self):
        self.config['refreshInterval'] = 30
        self.write_state(age=1200)
        account = self.collect()
        self.assertEqual(account['status'], 'ok')
        self.assertFalse((self.profile/'calls').exists())
        stored = json.loads(self.cache.read_text())['accounts'][account['id']]
        self.assertEqual(stored['nextAttempt'], account['updatedAt'] + 1800)

    def test_offline_never_starts_claude(self):
        self.collect(offline=True)
        self.assertFalse((self.profile/'calls').exists())

    def test_account_switch_cannot_reuse_the_previous_capture_or_history(self):
        first = self.credential()
        self.write_state(age=10, account='other-account', cache_account='account-one')
        second = self.credential()
        self.assertNotEqual(first['id'], second['id'])
        self.assertIsNone(claude.read(first, time.time()))
        self.assertIsNone(claude.read(second, time.time()))
        self.mode('switch')
        self.write_state(age=3600)
        result = self.collect()
        self.assertEqual(result['windows'], [])
        self.assertIn('account changed', result['message'])

    def test_switch_during_refresh_does_not_serve_old_widget_cache(self):
        first = self.collect()
        stored = json.loads(self.cache.read_text())
        stored['accounts'][first['id']]['lastAttempt'] = time.time()-30
        self.cache.write_text(json.dumps(stored))
        self.mode('switch')
        result = self.collect(force=True)
        self.assertEqual(result['windows'], [])
        self.assertIn('account changed', result['message'])

    def test_native_cached_reply_does_not_extend_freshness(self):
        self.write_state(age=60)
        state = json.loads((self.profile/'.claude.json').read_text())
        payload = state['cachedUsageUtilization']['utilization']
        with patch('collector.claude._request', return_value={'rate_limits_available':True,'rate_limits':payload}):
            result = self.collect(force=True)
        self.assertGreater(time.time()-result['updatedAt'], 59)
        stored = json.loads(self.cache.read_text())['accounts'][result['id']]
        self.assertEqual(stored['nextAttempt'], result['updatedAt']+300)

    def test_capture_comparison_tolerates_only_subsecond_reset_variation(self):
        self.write_state(age=60)
        path = self.profile / '.claude.json'
        state = json.loads(path.read_text())
        state['cachedUsageUtilization']['utilization']['five_hour']['resets_at'] = 1900000000.1
        path.write_text(json.dumps(state))
        for reset, used, accepted in ((1900000000.9, 40, True),
                                      (1900000002.1, 40, False),
                                      (1900000000.1, 41, False),
                                      (None, 40, False)):
            with self.subTest(reset=reset, used=used):
                response = {'rate_limits_available': True, 'rate_limits': {
                    'five_hour': {'utilization': used, 'resets_at': reset}}}
                with patch('collector.claude._request', return_value=response):
                    if accepted:
                        reading = claude.fetch(self.credential())
                        self.assertEqual(reading['fetchedAt'], state['cachedUsageUtilization']['fetchedAtMs']/1000)
                        self.assertEqual(reading['data']['windows'][0]['resetAt'], 1900000000.1)
                    else:
                        with self.assertRaisesRegex(UsageError, 'could not verify fresh'):
                            claude.fetch(self.credential())

    def test_ancient_capture_is_hidden_even_during_a_retry_wait(self):
        first = self.collect()
        stored = json.loads(self.cache.read_text())
        stored['accounts'][first['id']].update(updatedAt=time.time()-90000,
            retryNotBefore=time.time()+600, nextAttempt=time.time()+600)
        self.cache.write_text(json.dumps(stored))
        self.write_state(age=90000)
        self.assertEqual(self.collect(force=True)['windows'], [])
        self.assertEqual((self.profile/'calls').read_text().count('call'), 1)

    def test_success_with_missing_invalid_or_mismatched_capture_is_rejected(self):
        for mode in ('null','badshape'):
            with self.subTest(mode=mode):
                self.write_state(age=3600)
                self.mode(mode)
                with self.assertRaises(UsageError): claude.fetch(self.credential())
        self.write_state(age=-60)
        self.assertIsNone(claude.read(self.credential(), time.time()))

    def test_errors_do_not_publish_subprocess_output(self):
        self.mode('error')
        with self.assertRaises(UsageError) as caught: claude.fetch(self.credential())
        self.assertNotIn('NEVER-PUBLISH', str(caught.exception))

    def test_missing_binary_gives_actionable_error(self):
        with patch('collector.claude.shutil.which', return_value=None):
            with self.assertRaisesRegex(UsageError, 'not found'): claude.fetch(self.credential())

    def test_timeout_and_output_limit_terminate_the_process(self):
        self.mode('timeout')
        start = time.monotonic()
        with patch('collector.claude.TIMEOUT', .25):
            with self.assertRaisesRegex(UsageError, 'in time'): claude.fetch(self.credential())
        self.assertLess(time.monotonic()-start, 3)
        pid = int((self.profile/'pid').read_text())
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
        self.mode('flood')
        with patch('collector.claude.MAX_OUTPUT', 1000):
            with self.assertRaisesRegex(UsageError, 'too much output'): claude.fetch(self.credential())

    def test_force_obeys_provider_backoff_and_resumes_after_it(self):
        first = self.collect()
        stored = json.loads(self.cache.read_text())
        entry = stored['accounts'][first['id']]
        entry.update(status='stale', message='Provider rate limited this check.',
                     retryNotBefore=time.time()+600, nextAttempt=time.time()+600,
                     lastAttempt=time.time()-30)
        self.cache.write_text(json.dumps(stored))
        self.collect(force=True)
        self.assertEqual((self.profile/'calls').read_text().count('call'), 1)
        entry.update(retryNotBefore=time.time()-1, nextAttempt=time.time()-1)
        self.cache.write_text(json.dumps(stored))
        self.assertEqual(self.collect(force=True)['status'], 'ok')
        self.assertEqual((self.profile/'calls').read_text().count('call'), 2)

    def test_two_collector_processes_share_one_native_request(self):
        self.mode('slow')
        config = self.home / 'settings.json'
        config.write_text(json.dumps(self.config))
        script = """import sys
from pathlib import Path
from unittest.mock import patch
from collector.main import main
home = Path(sys.argv.pop(1))
with patch('pathlib.Path.home', return_value=home):
    main()
"""
        command = [sys.executable, '-c', script, str(self.home), '--config', str(config)]
        environment = {**os.environ, 'XDG_CACHE_HOME': str(self.home/'process-cache')}
        first = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic()+3
            while not (self.profile/'started').exists() and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertTrue((self.profile/'started').exists())
            second = subprocess.run(command, env=environment, capture_output=True, timeout=3)
            self.assertEqual(second.returncode, 0, second.stderr)
            output, stderr = first.communicate(timeout=3)
            self.assertEqual(first.returncode, 0, stderr)
            self.assertEqual(next(a for a in json.loads(output)['accounts'] if a['provider']=='claude')['status'], 'ok')
            self.assertEqual((self.profile/'calls').read_text().count('call'), 1)
        finally:
            if first.poll() is None:
                first.kill()
                first.communicate()


if __name__ == '__main__': unittest.main()
