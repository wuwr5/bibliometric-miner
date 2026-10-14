# -*- coding: utf-8 -*-
"""
server.py -- zero-dependency HTTP back end for the CiteSpace-like workbench.

    python server.py [port]        (default 8765)

Endpoints
    GET  /                      -> web/index.html
    GET  /web/<file>            -> static assets (also /assets/<file>)
    GET  /api/files             -> list of importable data files
    POST /api/upload            -> raw text body + X-Filename header
                                   saves into data/ and returns a summary
    POST /api/analyze           -> JSON params -> full analysis result
    POST /api/dualmap           -> dual-map overlay of citing/cited journals
    POST /api/geo               -> country collaboration network (world map)
    POST /api/structvar         -> structural variation analysis
    POST /api/topics            -> LDA / BERTopic-style topic modelling
    POST /api/citenet           -> internal citation network structure
    POST /api/forecast          -> trend forecasting + emerging topics
    POST /api/kbca              -> multi-channel fusion (KBCA) + value score
    GET  /api/cache/clear       -> drop the in-memory parsed documents
    GET  /api/shutdown          -> stop the server

Everything is plain standard library so the tool runs anywhere Python 3.8+
is available -- no pip install required.
"""

import os
import sys
import json
import time
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wos_parser as wos          # noqa: E402
import analyze as az              # noqa: E402
import dualmap as dmap            # noqa: E402
import geoview as gv              # noqa: E402
import structvar as sv            # noqa: E402
import topicmodel as tmod         # noqa: E402
import citenet as cnet            # noqa: E402
import forecast as fcst           # noqa: E402
import kbca as kmod               # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, 'web')
DATA = os.path.join(HERE, 'data')
SAMPLE = os.path.join(HERE, 'sample')
ASSETS = os.path.join(HERE, 'assets')

MIME = {'.html': 'text/html; charset=utf-8',
        '.css': 'text/css; charset=utf-8',
        '.js': 'application/javascript; charset=utf-8',
        '.json': 'application/json; charset=utf-8',
        '.svg': 'image/svg+xml',
        '.png': 'image/png',
        '.ico': 'image/x-icon'}

# file -> (docs, meta, mtime) so re-analyzing with new parameters is instant
_CACHE = {}
_LOCK = threading.Lock()


def _docs_for(path):
    key = os.path.abspath(path)
    mt = os.path.getmtime(key)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit[2] == mt:
            return hit[0]
    docs, meta = wos.parse_files([key])
    with _LOCK:
        _CACHE[key] = (docs, meta, mt)
    return docs


def list_files():
    out = []
    for folder, tag in ((DATA, 'uploaded'), (SAMPLE, 'sample')):
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            p = os.path.join(folder, fn)
            if os.path.isfile(p) and os.path.splitext(fn)[1].lower() in (
                    '.txt', '.ciw', '.csv'):
                out.append({'name': fn, 'path': p, 'group': tag,
                            'size': os.path.getsize(p)})
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    # ---------------------------------------------------------------- log
    def log_message(self, fmt, *args):
        sys.stderr.write('  %s - %s\n' % (self.path, fmt % args))

    # ------------------------------------------------------------ helpers
    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        return self.rfile.read(n) if n else b''

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/':
            path = '/index.html'
        if path.startswith('/api/'):
            return self.api_get(path)
        if path.startswith('/data/') or path.startswith('/sample/') or \
                path.startswith('/assets/'):
            rel = path[1:]
            full = os.path.join(HERE, rel)
            if os.path.isfile(full):
                return self._file(full)
            return self._send(404, b'not found')
        full = os.path.join(WEB, path.lstrip('/'))
        if not os.path.abspath(full).startswith(os.path.abspath(WEB)):
            return self._send(403, b'forbidden')
        if os.path.isfile(full):
            return self._file(full)
        self._send(404, b'not found')

    def _file(self, full):
        ext = os.path.splitext(full)[1].lower()
        with open(full, 'rb') as f:
            data = f.read()
        self._send(200, data, MIME.get(ext, 'application/octet-stream'))

    def api_get(self, path):
        if path == '/api/files':
            return self._json({'files': list_files(),
                               'data_dir': DATA, 'sample_dir': SAMPLE})
        if path == '/api/cache/clear':
            with _LOCK:
                _CACHE.clear()
            return self._json({'ok': True})
        if path == '/api/ping':
            return self._json({'ok': True, 'time': time.time()})
        if path == '/api/shutdown':
            threading.Thread(target=shutdown, daemon=True).start()
            return self._json({'ok': True})
        self._json({'error': 'unknown endpoint'}, 404)

    # --------------------------------------------------------------- POST
    def do_POST(self):
        path = self.path.split('?')[0]
        try:
            if path == '/api/upload':
                return self.api_upload()
            if path == '/api/analyze':
                return self.api_analyze()
            if path == '/api/parse':
                return self.api_parse()
            if path == '/api/dualmap':
                return self.api_dualmap()
            if path == '/api/geo':
                return self.api_geo()
            if path == '/api/structvar':
                return self.api_structvar()
            if path == '/api/topics':
                return self.api_topics()
            if path == '/api/citenet':
                return self.api_citenet()
            if path == '/api/forecast':
                return self.api_forecast()
            if path == '/api/kbca':
                return self.api_kbca()
            self._json({'error': 'unknown endpoint'}, 404)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({'error': '%s: %s' % (type(e).__name__, e)}, 500)

    def api_upload(self):
        from urllib.parse import unquote
        name = self.headers.get('X-Filename') or 'upload_%d.txt' % int(time.time())
        name = os.path.basename(unquote(name)).replace('..', '_')
        raw = self._body()
        # keep utf-8 if it decodes, otherwise write the original bytes
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('gb18030', errors='replace')
        if not os.path.isdir(DATA):
            os.makedirs(DATA, exist_ok=True)
        dest = os.path.join(DATA, name)
        with open(dest, 'w', encoding='utf-8') as f:
            f.write(text)
        docs, meta = wos.parse_files([dest])
        with _LOCK:
            _CACHE[os.path.abspath(dest)] = (docs, meta, os.path.getmtime(dest))
        return self._json({'ok': True, 'file': name, 'path': dest,
                           'n_records': len(docs),
                           'summary': wos.summarise(docs),
                           'files': list_files()})

    def api_parse(self):
        payload = json.loads(self._body().decode('utf-8') or '{}')
        paths = payload.get('files') or []
        docs = []
        for p in paths:
            docs.extend(_docs_for(p))
        return self._json({'n_docs': len(docs),
                           'summary': wos.summarise(docs)})

    def api_analyze(self):
        payload = json.loads(self._body().decode('utf-8') or '{}')
        paths = payload.get('files') or []
        params = payload.get('params') or {}
        if not paths:
            return self._json({'error': 'no files selected'}, 400)
        docs = []
        for p in paths:
            docs.extend(_docs_for(p))
        log = []
        res = az.run(docs, params, log)
        res['summary_dataset'] = wos.summarise(docs)
        res['source_files'] = [os.path.basename(p) for p in paths]
        return self._json(res)

    def _docs_from_body(self):
        payload = json.loads(self._body().decode('utf-8') or '{}')
        paths = payload.get('files') or []
        docs = []
        for p in paths:
            docs.extend(_docs_for(p))
        return docs, payload

    def api_dualmap(self):
        docs, payload = self._docs_from_body()
        if not docs:
            return self._json({'error': '未选择数据文件'}, 400)
        opts = payload.get('options') or {}
        res = dmap.build(docs,
                         min_docs=int(opts.get('min_docs', 1) or 1),
                         min_citations=int(opts.get('min_citations', 1) or 1),
                         top_flows=int(opts.get('top_flows', 600) or 600),
                         top_journals=int(opts.get('top_journals', 90) or 90))
        res['source_files'] = [os.path.basename(p)
                               for p in (payload.get('files') or [])]
        return self._json(res)

    def api_geo(self):
        docs, payload = self._docs_from_body()
        if not docs:
            return self._json({'error': '未选择数据文件'}, 400)
        opts = payload.get('options') or {}
        log = []
        res = gv.build(docs,
                       min_count=int(opts.get('min_count', 1) or 1),
                       top_edges=int(opts.get('top_edges', 400) or 400),
                       resolution=float(opts.get('resolution', 1.0) or 1.0),
                       log=log)
        res['log'] = log
        res['source_files'] = [os.path.basename(p)
                               for p in (payload.get('files') or [])]
        return self._json(res)

    def api_structvar(self):
        docs, payload = self._docs_from_body()
        if not docs:
            return self._json({'error': '未选择数据文件'}, 400)
        log = []
        res = sv.run(docs, payload.get('params') or {}, log)
        res['log'] = log
        res['source_files'] = [os.path.basename(p)
                               for p in (payload.get('files') or [])]
        return self._json(res)

    # ------------------------------------------------- 2026 round-3 additions
    def api_topics(self):
        docs, payload = self._docs_from_body()
        if not docs:
            return self._json({'error': '未选择数据文件'}, 400)
        log = []
        res = tmod.run(docs, payload.get('params') or {}, log)
        res['log'] = log
        res['source_files'] = [os.path.basename(p)
                               for p in (payload.get('files') or [])]
        return self._json(res)

    def api_citenet(self):
        docs, payload = self._docs_from_body()
        if not docs:
            return self._json({'error': '未选择数据文件'}, 400)
        log = []
        res = cnet.run(docs, payload.get('params') or {}, log)
        res['log'] = log
        res['source_files'] = [os.path.basename(p)
                               for p in (payload.get('files') or [])]
        return self._json(res)

    def api_forecast(self):
        docs, payload = self._docs_from_body()
        if not docs:
            return self._json({'error': '未选择数据文件'}, 400)
        log = []
        res = fcst.run(docs, payload.get('params') or {}, log)
        res['log'] = log
        res['source_files'] = [os.path.basename(p)
                               for p in (payload.get('files') or [])]
        return self._json(res)

    def api_kbca(self):
        docs, payload = self._docs_from_body()
        if not docs:
            return self._json({'error': '未选择数据文件'}, 400)
        log = []
        res = kmod.run(docs, payload.get('params') or {}, log)
        res['log'] = log
        res['source_files'] = [os.path.basename(p)
                               for p in (payload.get('files') or [])]
        return self._json(res)


SRV = None


def shutdown():
    if SRV:
        time.sleep(0.2)
        SRV.shutdown()


def main():
    global SRV
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    os.makedirs(DATA, exist_ok=True)
    SRV = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    url = 'http://127.0.0.1:%d/' % port
    print('=' * 62)
    print('  CiteSpace-like Bibliometric Workbench')
    print('  serving %s' % url)
    print('  data dir : %s' % DATA)
    print('  press Ctrl+C to stop')
    print('=' * 62)
    try:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    except Exception:
        pass
    try:
        SRV.serve_forever()
    except KeyboardInterrupt:
        print('\nbye')


if __name__ == '__main__':
    main()
