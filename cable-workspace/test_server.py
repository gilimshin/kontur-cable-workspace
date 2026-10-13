"""Integration checks use an isolated temporary database, never user records."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import server

class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        server.DB = Path(cls.tmp.name) / 'data' / 'test.sqlite3'
        server.initialize()
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.url = 'http://127.0.0.1:' + str(cls.http.server_port)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.tmp.cleanup()

    def request(self, path, method='GET', data=None, origin=None):
        headers={'Content-Type':'application/json'}
        if origin: headers['Origin']=origin
        request=Request(self.url+path, data=json.dumps(data).encode() if data else None, headers=headers, method=method)
        try:
            with urlopen(request) as r: return r.status,json.load(r)
        except HTTPError as e: return e.code,json.load(e)

    def test_import_matches_workbook(self):
        status, projects=self.request('/api/projects')
        self.assertEqual(status,200)
        p=next(p for p in projects if p['id']=='dubninskaya')
        self.assertEqual(len(p['cables']),8)
        self.assertEqual(len(p['catalog']),62)
        lengths=[int(c['ground']*1.02+c['hdd']+c['pipe']*1.01+c['entry']+.5) for c in p['cables']]
        self.assertEqual(lengths,[254,254,254,254,315,315,304,304])

    def test_save_persistence_conflict_and_validation(self):
        p=copy.deepcopy(self.request('/api/projects')[1][0])
        p['name']='Тестовый объект'
        status,p=self.request('/api/projects','POST',{'project':p,'actor':'Тест'})
        self.assertEqual(status,200)
        stale=copy.deepcopy(p)
        p['cables'][0]['entry']=50
        status,p=self.request('/api/projects','PUT',{'project':p,'actor':'Инженер'})
        self.assertEqual(status,200)
        saved=next(x for x in self.request('/api/projects')[1] if x['id']==p['id'])
        self.assertEqual(saved['cables'][0]['entry'],50)
        self.assertEqual(self.request('/api/projects','PUT',{'project':stale})[0],409)
        self.assertEqual(len(self.request('/api/events/'+p['id'])[1]),2)
        p['cables'][0]['ground']=-1
        self.assertEqual(self.request('/api/projects','PUT',{'project':p})[0],400)
        p['cables'][0]['ground']=1
        p['dates'][0]['start']='2026-10-13';p['dates'][0]['end']='2026-10-12'
        self.assertEqual(self.request('/api/projects','PUT',{'project':p})[0],400)
        self.assertEqual(self.request('/api/projects','POST',{'project':p},origin='https://example.com')[0],403)

if __name__=='__main__': unittest.main()
