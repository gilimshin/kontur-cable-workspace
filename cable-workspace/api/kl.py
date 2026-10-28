"""Расчёт КЛ по исполнительному чертежу (PDF) в облачной версии на Vercel.

Те же маршруты, что у локального server.py:
  GET  /api/kl/health  — проверка, что расчёт доступен
  POST /api/kl/parse   — PDF в теле запроса, параметры в строке запроса
  POST /api/kl/excel   — JSON {result, rows} -> .xlsx
Доступ только после входа по общему паролю (та же cookie, что у api/workspace.js).
"""
import base64
import hashlib
import hmac
import io
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Лимит Vercel на тело запроса и ответа — 4,5 МБ.
MAX_PDF = 4_400_000
MAX_IMAGE = 2_800_000


def b64url_decode(s):
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def valid_session(token, secret):
    """Повторяет validSession из lib/workspace.js."""
    try:
        body, signature = str(token).split('.', 1)
        expected = base64.urlsafe_b64encode(
            hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()).decode().rstrip('=')
        if not hmac.compare_digest(signature, expected):
            return False
        return json.loads(b64url_decode(body))['expires'] > time.time() * 1000
    except Exception:
        return False


def kl_modules():
    try:
        from kl_calc import calc
        from kl_calc.excel import build_xlsx
    except ImportError as e:
        raise RuntimeError('Модуль расчёта по PDF не установлен на сервере (' + str(e) + ')')
    original = getattr(calc.render_plan, 'original', calc.render_plan)

    def adaptive(data, bbox, w, h, scale=4.0):
        # Подложка чертежа должна уместиться в лимит ответа Vercel.
        r = {}
        for s in (scale, 3.0, 2.2, 1.6, 1.1):
            r = original(data, bbox, w, h, scale=s)
            if 'src' not in r or len(r['src']) <= MAX_IMAGE:
                return r
        return dict(error='Подложка чертежа слишком большая для облачной версии')

    adaptive.original = original
    calc.render_plan = adaptive
    return calc.compute, build_xlsx


class handler(BaseHTTPRequestHandler):
    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'private, no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        name = q.pop('route', None) or u.path.rstrip('/').rsplit('/', 1)[-1]
        return name, q

    def allowed(self):
        password = os.environ.get('WORKSPACE_PASSWORD') or ''
        if len(password) < 24:
            self.reply(503, {'error': 'Доступ ещё не настроен'})
            return False
        cookies = dict(c.strip().split('=', 1) for c in (self.headers.get('Cookie') or '').split(';') if '=' in c)
        if not valid_session(cookies.get('kontur_session', ''), password):
            self.reply(401, {'error': 'Войдите в рабочее пространство'})
            return False
        return True

    def do_GET(self):
        name, _ = self.route()
        if not self.allowed():
            return
        if name == 'health':
            try:
                kl_modules()
                return self.reply(200, {'ok': True, 'kl': True, 'cloud': True, 'maxPdf': MAX_PDF})
            except RuntimeError as e:
                return self.reply(200, {'ok': True, 'kl': False, 'error': str(e)})
        return self.reply(404, {'error': 'Не найдено'})

    def do_POST(self):
        name, q = self.route()
        if not self.allowed():
            return
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            return self.reply(403, {'error': 'Недопустимый источник запроса'})
        try:
            size = int(self.headers.get('Content-Length') or 0)
            if size > MAX_PDF:
                return self.reply(413, {'error': 'Файл больше 4 МБ — в облачной версии такой чертёж не принимается. '
                                                 'Уменьшите PDF или посчитайте в локальной версии.'})
            body = self.rfile.read(size)
            compute, build_xlsx = kl_modules()
            if name == 'parse':
                if not body.startswith(b'%PDF-'):
                    return self.reply(400, {'error': 'Нужен PDF исполнительного чертежа (векторный, выгруженный из CAD)'})
                res = compute(io.BytesIO(body),
                              zavodka_default=(float(q.get('zav_from', 5)), float(q.get('zav_to', 5))),
                              k_ground=float(q.get('k_ground', 1.02)), k_pipe=float(q.get('k_pipe', 1.01)))
                return self.reply(200, res)
            if name == 'excel':
                payload = json.loads(body or b'{}')
                if not payload.get('result'):
                    return self.reply(400, {'error': 'Нет данных расчёта'})
                x = build_xlsx(payload['result'], payload.get('rows'))
                self.send_response(200)
                self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                self.send_header('Content-Disposition', 'attachment; filename="KL_raschet.xlsx"')
                self.send_header('Cache-Control', 'private, no-store')
                self.send_header('Content-Length', str(len(x)))
                self.end_headers()
                self.wfile.write(x)
                return
            return self.reply(404, {'error': 'Не найдено'})
        except RuntimeError as e:
            return self.reply(501, {'error': str(e)})
        except ValueError as e:
            return self.reply(422, {'error': str(e)})
        except Exception as e:
            print('KL calculation failed:', type(e).__name__, e, flush=True)
            return self.reply(500, {'error': 'Ошибка расчёта: ' + str(e)})
