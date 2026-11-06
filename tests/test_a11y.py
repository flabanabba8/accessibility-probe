import importlib.util
import os
from unittest.mock import Mock, patch
import http.server
import threading
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('a11y_core', Path(__file__).parents[1] / 'core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

class AccessibilityTests(unittest.TestCase):
    def test_replacement_during_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            page = Path(tmp)/'page.html'; page.write_text('<button>First</button>')
            replacement = Path(tmp)/'replacement'; replacement.write_text('<button>Second</button>')
            original = core.os.fstat; calls = 0
            def replace(fd):
                nonlocal calls
                calls += 1
                value = original(fd)
                if calls == 2: os.replace(replacement, page)
                return value
            with patch.object(core.os, 'fstat', side_effect=replace):
                with self.assertRaisesRegex(ValueError, 'changed while reading'): core.inspect_html(str(page))

    def test_find_and_distinguish_labels(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            p = Path(tmp) / 'page.html'
            p.write_text('<img src="x"><img alt=""><label for="a">Name</label><input id="a"><input id="b"><button></button><button aria-label="Save"></button><a href="/">Go</a><div id="a"></div>')
            result = core.inspect_html(str(p))
            kinds = [x['kind'] for x in result['issues']]
            self.assertEqual(kinds.count('image_missing_alt'), 1)
            self.assertEqual(kinds.count('possible_missing_accessible_name'), 2)
            self.assertIn('duplicate_id', kinds)

    def test_nested_label_and_labelledby(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            p = Path(tmp) / 'page.html'
            p.write_text('<span id="label">Email</span><input aria-labelledby="label"><label>Age<input></label>')
            self.assertEqual(core.inspect_html(str(p))['issues'], [])

class KeyboardTests(unittest.TestCase):
    def test_browser_subprocess_does_not_inherit_credentials(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            p = Path(tmp) / 'page.html'
            p.write_text('<button id="ok">OK</button>')
            process = Mock()
            process.returncode = 0
            process.communicate.return_value = (b'{"steps": []}', None)
            process.__enter__ = Mock(return_value=process)
            process.__exit__ = Mock(return_value=False)
            with patch.dict(os.environ, {'INWORLD_API_KEY': 'fixture-only-value'}), patch.object(core.subprocess, 'Popen', return_value=process) as run:
                core.keyboard_walk(str(p), ['#ok'])
            child_env = run.call_args.kwargs['env']
            self.assertNotIn('INWORLD_API_KEY', child_env)
            self.assertEqual(set(child_env), {'PATH', 'LANG'})

    def test_timeout_stops_owned_process_group(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            p = Path(tmp) / 'page.html'
            p.write_text('<button id="ok">OK</button>')
            process = Mock()
            process.pid = 98765
            process.__enter__ = Mock(return_value=process)
            process.__exit__ = Mock(return_value=False)
            process.communicate.side_effect = [core.subprocess.TimeoutExpired('fixture', 45), (b'', None)]
            with patch.object(core.subprocess, 'Popen', return_value=process), patch.object(core.os, 'killpg') as kill:
                with self.assertRaisesRegex(RuntimeError, 'timed out'):
                    core.keyboard_walk(str(p), ['#ok'])
            kill.assert_called_once_with(process.pid, core.signal.SIGKILL)

    def test_external_resources_are_blocked(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            requests = 0
            def do_GET(self):
                type(self).requests += 1
                self.send_response(204)
                self.end_headers()
            def log_message(self, *args): pass
        server = http.server.HTTPServer(('localhost', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
                p = Path(tmp) / 'page.html'
                p.write_text(f'<img src="http://localhost:{server.server_port}/image"><button id="ok">OK</button>')
                result = core.keyboard_walk(str(p), ['#ok'])
                self.assertTrue(result['steps'][0]['matches_expected'])
                self.assertEqual(Handler.requests, 0)
        finally:
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()

    def test_headless_tab_order_and_script_disabled(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
            p = Path(tmp) / 'journey.html'
            p.write_text('<button id="first">First</button><a id="second" href="/other">Second</a><button id="third">Third</button><script>document.getElementById("third").focus()</script>')
            result = core.keyboard_walk(str(p), ['#first', '#second', '#third'])
            self.assertEqual([x['id'] for x in result['steps']], ['first', 'second', 'third'])
            self.assertTrue(all(x['matches_expected'] for x in result['steps']))
            mismatch = core.keyboard_walk(str(p), ['#second'])
            self.assertFalse(mismatch['steps'][0]['matches_expected'])

if __name__ == '__main__':
    unittest.main()
