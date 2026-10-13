import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from import_source import extract

MAX_PDF = 60 * 1024 * 1024


def kl_modules():
    """Расчёт КЛ по исполнительному чертежу (PDF). Нужны pdfplumber и openpyxl."""
    try:
        from kl_calc import compute
        from kl_calc.excel import build_xlsx
        return compute, build_xlsx
    except ImportError as e:
        raise RuntimeError('Для расчёта по PDF установите библиотеки: pip install pdfplumber openpyxl (' + str(e) + ')')

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data' / 'workspace.sqlite3'
SOURCE = Path(os.environ.get('SOURCE_WORKBOOK', str(Path.home() / 'Downloads' / '0,4кВ МАКРОС.xlsm')))

def connect():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    return db

def initialize():
    DB.parent.mkdir(exist_ok=True)
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, project TEXT, actor TEXT, action TEXT, time TEXT)')
        if db.execute('SELECT count(*) FROM projects').fetchone()[0] == 0 and SOURCE.exists():
            p = extract(SOURCE)
            db.execute('INSERT INTO projects VALUES (?,?)', (p['id'], json.dumps(p,ensure_ascii=False)))
            db.execute('INSERT INTO events(project,actor,action,time) VALUES (?,?,?,?)', (p['id'],'Система','Импортированы исходные данные Excel',datetime.now(timezone.utc).isoformat()))

def validate(p):
    if not isinstance(p,dict) or not isinstance(p.get('name'),str) or not p['name'].strip(): raise ValueError('Укажите название объекта')
    for field in ['cables','dates','materials','notes','catalog']:
        if not isinstance(p.get(field),list) or len(p[field]) > 2000: raise ValueError('Некорректные данные: '+field)
    for c in p['cables']:
        for k in ['ground','hdd','pipe','entry']:
            v=c.get(k)
            if not isinstance(v,(int,float)) or not 0 <= v <= 1000000: raise ValueError('Длины должны быть неотрицательными числами')
    for d in p['dates']:
        for k in ['start','end']:
            if d.get(k): datetime.strptime(d[k],'%Y-%m-%d')
        if d.get('start') and d.get('end') and d['end'] < d['start']: raise ValueError('Окончание работ раньше начала')

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(ROOT/'public'),**kwargs)
    def response(self,status,data):
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/projects':
            with connect() as db: items=[json.loads(r['body']) for r in db.execute('SELECT body FROM projects')]
            return self.response(200,items)
        if path.startswith('/api/events/'):
            with connect() as db: rows=[dict(r) for r in db.execute('SELECT * FROM events WHERE project=? ORDER BY id DESC LIMIT 100',(path.split('/')[-1],))]
            return self.response(200,rows)
        if path=='/api/kl/health':
            try: kl_modules(); return self.response(200,{'ok':True,'kl':True})
            except RuntimeError as e: return self.response(200,{'ok':True,'kl':False,'error':str(e)})
        if path.startswith('/api/'): return self.response(404,{'error':'Не найдено'})
        return super().do_GET()
    def do_POST(self):
        if urlparse(self.path).path.startswith('/api/kl/'): return self.kl()
        self.save(True)
    def kl(self):
        from urllib.parse import parse_qs
        if self.headers.get('Origin') and self.headers['Origin'] not in ['http://127.0.0.1:8765','http://localhost:8765']: return self.response(403,{'error':'Недопустимый источник запроса'})
        u=urlparse(self.path); q={k:v[0] for k,v in parse_qs(u.query).items()}
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>MAX_PDF: return self.response(413,{'error':'Файл слишком большой'})
            body=self.rfile.read(size)
            compute, build_xlsx = kl_modules()
            if u.path=='/api/kl/parse':
                if not body.startswith(b'%PDF-'): return self.response(400,{'error':'Нужен PDF исполнительного чертежа (векторный, выгруженный из CAD)'})
                import io
                res=compute(io.BytesIO(body), zavodka_default=(float(q.get('zav_from',5)),float(q.get('zav_to',5))), k_ground=float(q.get('k_ground',1.02)), k_pipe=float(q.get('k_pipe',1.01)))
                return self.response(200,res)
            if u.path=='/api/kl/excel':
                payload=json.loads(body or b'{}')
                if not payload.get('result'): return self.response(400,{'error':'Нет данных расчёта'})
                x=build_xlsx(payload['result'],payload.get('rows'))
                self.send_response(200); self.send_header('Content-Type','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'); self.send_header('Content-Disposition','attachment; filename="KL_raschet.xlsx"'); self.send_header('Content-Length',str(len(x))); self.end_headers(); self.wfile.write(x); return
            return self.response(404,{'error':'Не найдено'})
        except RuntimeError as e: return self.response(501,{'error':str(e)})
        except ValueError as e: return self.response(422,{'error':str(e)})
        except Exception as e:
            import traceback; traceback.print_exc()
            return self.response(500,{'error':'Ошибка расчёта: '+str(e)})
    def do_PUT(self): self.save(False)
    def save(self,create):
        if self.path!='/api/projects': return self.response(404,{'error':'Не найдено'})
        if self.headers.get('Origin') and self.headers['Origin'] not in ['http://127.0.0.1:8765','http://localhost:8765']: return self.response(403,{'error':'Недопустимый источник запроса'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>2_000_000: return self.response(413,{'error':'Слишком большой запрос'})
            payload=json.loads(self.rfile.read(size)); p=payload['project']; validate(p)
            actor=str(payload.get('actor','Локальный пользователь'))[:100]
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if create:
                    p['id']=uuid.uuid4().hex; p['revision']=1
                    action='Создан объект'
                    db.execute('INSERT INTO projects VALUES (?,?)',(p['id'],json.dumps(p,ensure_ascii=False)))
                else:
                    old=db.execute('SELECT body FROM projects WHERE id=?',(p['id'],)).fetchone()
                    if not old: return self.response(404,{'error':'Объект не найден'})
                    previous=json.loads(old['body'])
                    if previous['revision']!=p.get('revision'): return self.response(409,{'error':'Объект уже изменён в другом окне. Скопируйте свои изменения и обновите страницу.'})
                    if p == previous: return self.response(200,previous)
                    p['revision']+=1
                    changed=[k for k in p if k not in ['revision','id'] and p[k]!=previous.get(k)]
                    labels={'cables':'кабельные линии','dates':'даты работ','materials':'материалы','notes':'заметки','owner':'ответственный','status':'статус'}
                    action='Обновлено: '+', '.join(labels.get(k,'реквизиты') for k in changed)
                    db.execute('UPDATE projects SET body=? WHERE id=?',(json.dumps(p,ensure_ascii=False),p['id']))
                db.execute('INSERT INTO events(project,actor,action,time) VALUES (?,?,?,?)',(p['id'],actor,action,datetime.now(timezone.utc).isoformat()))
            self.response(200,p)
        except (ValueError,KeyError,TypeError) as e: self.response(400,{'error':str(e)})

if __name__=='__main__':
    initialize()
    print('Локальный сервис: http://127.0.0.1:8765',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
