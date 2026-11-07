"""Narrow static HTML labeling checks, not an accessibility conformance audit."""
from html.parser import HTMLParser
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path

PRIVATE = {'.ssh', '.gnupg', '.aws', '.azure', '.codex', '.docker', '.kube', '.pki', '.config', '.hermes'}
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if len(self.nodes) >= 100000 or len(self.stack) >= 256:
            raise ValueError('HTML element or nesting limit exceeded')
        data = dict(attrs)
        node = {'tag': tag, 'attrs': data, 'line': self.getpos()[0], 'text': '', 'parents': tuple(self.stack)}
        idx = len(self.nodes)
        self.nodes.append(node)
        if tag not in VOID: self.stack.append(idx)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack: self.stack.pop()

    def handle_endtag(self, tag):
        for position in range(len(self.stack) - 1, -1, -1):
            if self.nodes[self.stack[position]]['tag'] == tag:
                del self.stack[position:]
                return

    def handle_data(self, data):
        for idx in self.stack:
            self.nodes[idx]['text'] = (self.nodes[idx]['text'] + data)[:4096]


def read_html(source_path):
    p = Path(source_path).expanduser()
    if p.is_symlink() or any(x.casefold() in PRIVATE for x in p.parts): raise ValueError('Private paths and symlink inputs are unsupported')
    p = p.resolve(strict=True)
    if not p.is_file() or any(x.casefold() in PRIVATE for x in p.parts): raise ValueError('Choose a local HTML file outside private configuration')
    fd = os.open(p, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as f:
        before = os.fstat(f.fileno())
        if not stat.S_ISREG(before.st_mode): raise ValueError('Choose a regular HTML file')
        raw = f.read(4 * 1024**2 + 1)
        after = os.fstat(f.fileno())
    if len(raw) > 4 * 1024**2: raise ValueError('HTML exceeds 4 MiB')
    current = p.lstat()
    identity = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns)
    if identity(before) != identity(after) or identity(after) != identity(current) or not stat.S_ISREG(current.st_mode):
        raise ValueError('HTML changed while reading')
    return raw


def inspect_html(source_path):
    raw = read_html(source_path)
    parser = Parser()
    parser.feed(raw.decode('utf-8-sig'))
    nodes = parser.nodes
    if len(nodes) > 100000: raise ValueError('Too many HTML elements')
    ids, labels, issues = {}, set(), []
    for i, node in enumerate(nodes):
        attrs = node['attrs']
        ident = attrs.get('id')
        if ident:
            if ident in ids: issues.append({'line': node['line'], 'kind': 'duplicate_id', 'element': node['tag']})
            else: ids[ident] = i
        if node['tag'] == 'label' and attrs.get('for') and node['text'].strip(): labels.add(attrs['for'])
    for node in nodes:
        tag, attrs = node['tag'], node['attrs']
        if tag == 'img' and 'alt' not in attrs:
            issues.append({'line': node['line'], 'kind': 'image_missing_alt', 'element': tag})
        if tag not in ('input', 'textarea', 'select', 'button', 'a'): continue
        if tag == 'a' and not attrs.get('href'): continue
        if tag == 'input' and (attrs.get('type') or 'text').lower() in ('hidden', 'submit', 'reset', 'button', 'image'): continue
        labelledby = (attrs.get('aria-labelledby') or '').split()
        aria_named = bool((attrs.get('aria-label') or '').strip()) or any(ref in ids and nodes[ids[ref]]['text'].strip() for ref in labelledby)
        inline_label = any(nodes[x]['tag'] == 'label' and nodes[x]['text'].strip() for x in node['parents'])
        for_label = bool(attrs.get('id') in labels)
        visible_text = bool(node['text'].strip()) if tag in ('button', 'a') else False
        name_exists = aria_named or inline_label or for_label or visible_text
        if not name_exists:
            issues.append({'line': node['line'], 'kind': 'possible_missing_accessible_name', 'element': tag})
    return {'fingerprint': hashlib.sha256(raw).hexdigest(), 'elements': len(nodes), 'issues': issues,
            'notice': 'Static heuristics only: CSS visibility, JavaScript, images inside links, accessible-name computation, focus order and screen-reader behavior require browser testing.'}


def keyboard_walk(source_path, expected_selectors):
    """Press Tab in a separate, credential-scrubbed headless browser process."""
    import shutil
    if not isinstance(expected_selectors, list) or not 1 <= len(expected_selectors) <= 30 or any(not isinstance(x, str) or not x.strip() or len(x) > 300 for x in expected_selectors):
        raise ValueError('Provide 1–30 expected CSS selectors')
    raw = read_html(source_path)
    content = raw.decode('utf-8-sig')
    browser_path = shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
    if not browser_path and sys.platform == 'win32':
        browser_path = shutil.which('msedge') or next((str(p) for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')
            if os.environ.get(key) for p in (Path(os.environ[key]) / 'Microsoft' / 'Edge' / 'Application' / 'msedge.exe',) if p.is_file()), None)
    if not browser_path:
        raise ValueError('Install a compatible Chrome, Chromium or Microsoft Edge executable')
    payload = json.dumps({'content': content, 'expected_selectors': expected_selectors, 'browser_path': browser_path}).encode()
    if sys.platform == 'win32':
        system_root = os.environ.get('SYSTEMROOT', '')
        if not system_root: raise ValueError('Windows system root is required for browser cleanup')
        child_env = {key: os.environ[key] for key in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP') if key in os.environ}
        child_env['PATH'] = str(Path(system_root) / 'System32')
        process_options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        child_env = {'PATH': os.defpath, 'LANG': 'C.UTF-8'}
        process_options = {'start_new_session': True}
    try:
        with subprocess.Popen([sys.executable, '-I', str(Path(__file__).with_name('browser_worker.py'))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=child_env, **process_options) as process:
            try:
                output, _ = process.communicate(input=payload, timeout=45)
            except subprocess.TimeoutExpired as exc:
                if sys.platform == 'win32':
                    try:
                        subprocess.run([str(Path(system_root) / 'System32' / 'taskkill.exe'), '/PID', str(process.pid), '/T', '/F'], env=child_env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    if process.poll() is None: process.kill()
                else:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                process.communicate()
                raise RuntimeError('Headless browser walkthrough timed out') from exc
            if process.returncode or len(output) > 1024 * 1024:
                raise RuntimeError('Headless browser walkthrough failed; verify Playwright, browser and selectors')
    except OSError as exc:
        raise RuntimeError('Headless browser walkthrough did not start') from exc
    try:
        steps = json.loads(output)['steps']
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError('Headless browser returned an invalid result') from exc
    return {'fingerprint': hashlib.sha256(raw).hexdigest(), 'steps': steps,
            'notice': 'JavaScript and network are disabled. This is a local static-page focus walkthrough, not a screen-reader, visual focus, dynamic-app or conformance test.'}
