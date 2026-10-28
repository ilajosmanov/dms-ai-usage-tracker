import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from collector import activity
from collector.jsonfile import atomic_json
from collector.main import cached_snapshot, collect


class ActivityLimitTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.cache = self.home / 'cache/activity.json'
        self.now = time.time()
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def turn(self, model='claude-opus-5', tokens=100):
        return json.dumps({'timestamp': self.now, 'message': {
            'model': model, 'usage': {'input_tokens': tokens}}}).encode() + b'\n'

    def log(self, content):
        path = self.home / '.claude/projects/session.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_large_file_resumes_across_bounded_scans_without_double_counting(self):
        record = self.turn()
        self.log(record * 3)
        for expected in (100, 200, 300):
            result = activity.scan(self.cache, self.home, self.now, budget=len(record))
            self.assertEqual(result['claude'][0]['tokens'], expected)
        with patch('collector.activity.scan_turns', side_effect=AssertionError('rescanned complete log')):
            self.assertEqual(activity.scan(self.cache, self.home, self.now)['claude'][0]['tokens'], 300)

    def test_incomplete_record_still_consumes_the_io_budget(self):
        path = self.log(self.turn() * 20)
        days = {}
        offset, consumed = activity.scan_turns(path, 'claude', 0, days, budget=10)
        self.assertEqual(offset, 0)
        self.assertEqual(consumed, 10)
        self.assertEqual(days, {})

    def test_oversized_records_are_skipped_without_losing_following_turns(self):
        path = self.log(b'x' * 1000 + b'\n' + self.turn())
        with patch('collector.activity.MAX_RECORD_BYTES', 256):
            result = activity.scan(self.cache, self.home, self.now)
        self.assertEqual(result['claude'][0]['tokens'], 100)
        self.assertEqual(json.loads(self.cache.read_text())['files'][str(path)]['offset'], path.stat().st_size)

    def test_codex_head_scan_stops_even_when_no_model_is_found(self):
        class TrackedStream(io.BytesIO):
            consumed = 0

            def readline(self, size=-1):
                data = super().readline(size)
                self.consumed += len(data)
                return data

        stream = TrackedStream((json.dumps({'unrelated': 'record'}).encode() + b'\n') * 100)
        path = Mock()
        path.stat.return_value.st_mtime = self.now
        path.open.return_value = stream
        with patch('collector.activity.MAX_HEAD_BYTES', 64), patch('collector.activity.MAX_TAIL_BYTES', 64):
            activity.scan_codex(path, {})
        self.assertLessEqual(stream.consumed, 128)

    def test_codex_model_after_large_session_metadata_is_still_counted(self):
        path = self.home / '.codex/sessions/session.jsonl'
        path.parent.mkdir(parents=True)
        rows = [
            {'type': 'session_meta', 'payload': {'instructions': 'x' * 150000}},
            {'type': 'turn_context', 'payload': {'model': 'gpt-6'}},
            {'type': 'message', 'payload': {'content': 'x' * 300000}},
            {'timestamp': self.now, 'payload': {'type': 'token_count',
             'info': {'total_token_usage': {'total_tokens': 500}}}},
        ]
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        result = activity.scan(self.cache, self.home, self.now)
        self.assertEqual(result['codex'], [{'name': 'GPT-6', 'tokens': 500}])

    def test_codex_read_failure_does_not_mark_unread_log_complete(self):
        path = self.home / '.codex/sessions/session.jsonl'
        path.parent.mkdir(parents=True)
        rows = [
            {'type': 'turn_context', 'payload': {'model': 'gpt-6'}},
            {'timestamp': self.now, 'payload': {'type': 'token_count',
             'info': {'total_token_usage': {'total_tokens': 500}}}},
        ]
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        original = Path.open

        def interrupted_open(candidate, *args, **kwargs):
            if candidate == path:
                raise PermissionError('temporary access failure')
            return original(candidate, *args, **kwargs)

        with patch('pathlib.Path.open', interrupted_open):
            self.assertEqual(activity.scan(self.cache, self.home, self.now)['codex'], [])
        recovered = activity.scan(self.cache, self.home, self.now)
        self.assertEqual(recovered['codex'], [{'name': 'GPT-6', 'tokens': 500}])

    def test_nonfinite_counts_and_short_model_ids_do_not_break_collection(self):
        self.log(self.turn(tokens=float('inf')) + self.turn(model='gpt') + self.turn())
        result = activity.scan(self.cache, self.home, self.now)
        self.assertEqual(sum(model['tokens'] for model in result['claude']), 200)
        json.dumps(result, allow_nan=False)

    def test_cache_only_mode_does_not_walk_sessions_or_query_databases(self):
        self.log(self.turn())
        activity.scan(self.cache, self.home, self.now)
        with patch('collector.activity._in_window', side_effect=AssertionError('session walk')), \
                patch('collector.activity.scan_opencode', side_effect=AssertionError('database query')):
            result = activity.scan(self.cache, self.home, self.now, budget=0)
        self.assertEqual(result['claude'][0]['tokens'], 100)

    def test_unchanged_activity_does_not_rewrite_cache(self):
        self.log(self.turn())
        activity.scan(self.cache, self.home, self.now)
        with patch('collector.activity.atomic_json', side_effect=AssertionError('unchanged cache rewritten')):
            activity.scan(self.cache, self.home, self.now)

    def test_corrupt_activity_cache_is_rebuilt(self):
        self.log(self.turn())
        atomic_json(self.cache, {'version': activity.CACHE_VERSION, 'files': {'bogus': [], str(self.home / '.claude/projects/session.jsonl'): {
            'offset': 'invalid', 'size': None, 'days': []}}})
        result = activity.scan(self.cache, self.home, self.now)
        self.assertEqual(result['claude'][0]['tokens'], 100)

    def test_cache_only_mode_keeps_opencode_totals(self):
        def capture(path, days, cutoff, now):
            days[activity.day_of(now, now)] = {'GPT-6': 500}
        with patch('collector.activity.scan_opencode', side_effect=capture):
            activity.scan(self.cache, self.home, self.now)
        with patch('collector.activity.scan_opencode', side_effect=AssertionError('database query')):
            result = activity.scan(self.cache, self.home, self.now, budget=0)
        self.assertEqual(result['codex'], [{'name': 'GPT-6', 'tokens': 500}])

    def test_invalid_quota_cache_does_not_block_collection(self):
        path = self.home / 'cache/usage.json'
        for accounts in ([], {'bad': []}, {'bad': {'provider': 'codex', 'windows': [None]}},
                         {'bad': {'provider': 'codex', 'nextAttempt': 'tomorrow'}}):
            atomic_json(path, {'accounts': accounts})
            with patch('collector.main.discover', return_value={}):
                result = collect({}, path, home=self.home)
            self.assertEqual({a['status'] for a in result['accounts']}, {'missing'})
            atomic_json(path, {'accounts': accounts})
            self.assertEqual(len(cached_snapshot(path, self.now)['accounts']), 2)
