"""Pipe this output directly to migrate_to_blob.mjs; contains private project data."""
import json
import sqlite3
from pathlib import Path

db=sqlite3.connect('file:'+str(Path(__file__).resolve().parents[1]/'data'/'workspace.sqlite3')+'?mode=ro',uri=True)
db.row_factory=sqlite3.Row
state={'projects':[json.loads(r['body']) for r in db.execute('SELECT body FROM projects')], 'events':[dict(r) for r in db.execute('SELECT * FROM events ORDER BY id')]}
print(json.dumps(state,ensure_ascii=False))
