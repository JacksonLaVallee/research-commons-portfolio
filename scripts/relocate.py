"""Repair immutable-upload paths after copying .workspace to another computer.
Run with the app stopped: python scripts/relocate.py
"""
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import db
changed=0
for f in (Path(db.WORKSPACE)/'projects').glob('*/platform.sqlite'):
    c=db.connect(f.parent.name)
    try:
        with db.tx(c):
            for u in c.execute('SELECT * FROM upload').fetchall():
                filename=Path(u['path'].replace('\\','/')).name
                target=f.parent/'data'/filename
                if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=u['sha256']:
                    print('Missing or changed input:',f.parent.name,u['name']);continue
                c.execute('UPDATE upload SET path=? WHERE id=?',(str(target),u['id']))
                if u['imported_id']: db.update_props(c,u['imported_id'],path=str(target))
                changed+=1
    finally:c.close()
print('Verified and repaired',changed,'upload paths.')
