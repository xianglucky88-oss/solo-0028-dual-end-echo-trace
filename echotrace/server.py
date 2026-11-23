import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from .archive import Archive
from .contract import ContractError, canonical, decode
from .service import Workbench


ROOT = Path(__file__).resolve().parents[1]
CONFIG = decode((ROOT / 'workbench.json').read_bytes())
PREFIX = '/' + CONFIG['namespace'] + '/api/'
STATIC = {
    '/': ('index.html', 'text/html'),
    '/ui.js': ('ui.js', 'text/javascript'),
    '/chart.js': ('chart.js', 'text/javascript'),
    '/version-panel.js': ('version-panel.js', 'text/javascript'),
    '/result-table.js': ('result-table.js', 'text/javascript'),
    '/style.css': ('style.css', 'text/css'),
}
BODY_LIMIT = 512 * 1024


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(8)

    def response(self, payload, status=200, mime='application/json', filename=None):
        self.send_response(status)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; object-src 'none'; base-uri 'none'")
        if filename is not None:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(payload)

    def route(self, method):
        path = urlsplit(self.path).path
        if method == 'GET' and path in STATIC:
            file, mime = STATIC[path]
            self.response((ROOT / 'web' / file).read_bytes(), mime=mime)
            return
        if not path.startswith(PREFIX):
            raise ContractError('没有这个入口', 404)
        action = path[len(PREFIX):]
        wb = self.server.workbench
        if method == 'POST':
            if self.headers.get_content_type() != 'application/json':
                raise ContractError('应提交 JSON 数据', 415)
            length = self.headers.get('Content-Length', '')
            if not length.isascii() or not length.isdecimal() or len(length) > 8:
                raise ContractError('缺少合法的请求体长度', 411)
            if not 0 < int(length) <= BODY_LIMIT:
                raise ContractError('数据包超过 512 KiB 或为空', 413)
            body = self.rfile.read(int(length))
            if len(body) != int(length):
                raise ContractError('数据包传输未完成')
            self.response(canonical(wb.execute(action, decode(body))))
            return
        if action == 'config':
            self.response(canonical(CONFIG))
        elif action in ('sample', 'alternate', 'review-sample', 'review-alternate'):
            self.response((ROOT / 'examples' / (action + '.json')).read_bytes())
        elif action == 'revisions':
            self.response(canonical(wb.archive.list()))
        elif action.startswith(('packet/', 'export/')):
            command, key = action.split('/', 1)
            packet = wb.read(key)
            filename = f'{CONFIG["namespace"]}-{key[:16]}.json' if command == 'export' else None
            self.response(canonical(packet), filename=filename)
        else:
            raise ContractError('没有这个入口', 404)

    def handle_request(self, method):
        try:
            self.route(method)
        except ContractError as exc:
            self.response(canonical({'error': str(exc)}), exc.status)
        except sqlite3.OperationalError:
            logging.exception('成果库操作未完成')
            self.response(canonical({'error': '成果库暂时不可写入或读取'}), 503)
        except (TimeoutError, BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def do_GET(self):
        self.handle_request('GET')

    def do_POST(self):
        self.handle_request('POST')


def serve(db, port):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    try:
        server.workbench = Workbench(Archive(db), CONFIG)
    except BaseException:
        server.server_close()
        raise
    return server


def main():
    parser = argparse.ArgumentParser(description=CONFIG['title'])
    parser.add_argument('--port', type=int, default=CONFIG['port'], help='本机服务端口')
    parser.add_argument('--db', type=Path, default=ROOT / '.local' / (CONFIG['namespace'] + '.sqlite'), help='成果库文件')
    options = parser.parse_args()
    with serve(options.db, options.port) as server:
        print(f'{CONFIG["title"]}：http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
