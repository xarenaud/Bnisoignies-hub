import ast
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
import reminder17


class Reminder17Tests(unittest.TestCase):
    def test_schedule_filters_gauge_and_withdrawal(self):
        with tempfile.TemporaryDirectory() as root:
            db_path = Path(root) / 'test.sqlite'
            def database():
                db = sqlite3.connect(db_path)
                db.row_factory = sqlite3.Row
                return db
            with database() as db:
                db.executescript("""CREATE TABLE registrations(payload TEXT,count INTEGER,is_test INTEGER);
                    CREATE TABLE invitation_campaigns(id TEXT PRIMARY KEY,due REAL,subject TEXT,html TEXT,created_at TEXT);
                    CREATE TABLE invitation_campaign_recipients(campaign_id TEXT,email TEXT,status TEXT DEFAULT 'pending',claimed_at REAL,sent_at TEXT,error TEXT,PRIMARY KEY(campaign_id,email));""")
                db.execute('INSERT INTO invitation_campaigns VALUES(?,?,?,?,?)', (reminder17.SOURCE,0,'old','old','old'))
                emails = ['xavier@cx-com.be'] + ['u%s@example.com' % i for i in range(1,315)]
                db.executemany('INSERT INTO invitation_campaign_recipients(campaign_id,email,status) VALUES(?,?,?)', [(reminder17.SOURCE,e,'accepted_by_smtp') for e in emails])
                db.executemany('INSERT INTO registrations VALUES(?,?,?)', [(json.dumps({'email':'xavier@cx-com.be'}),1,0),(json.dumps({'email':'u1@example.com'}),2,0),(json.dumps({'email':'u2@example.com'}),20,1)])
            source = ast.parse((Path(__file__).parent / 'app.py').read_text())
            function = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'exclude_registered_campaign_recipients')
            namespace = {'time':reminder17.time}
            exec(compile(ast.Module(body=[function],type_ignores=[]),'registration-filter','exec'),namespace)
            exclude_registered = namespace['exclude_registered_campaign_recipients']
            app = Flask('reminder17-test', static_folder=str(Path(__file__).parent / 'static'))
            with patch('reminder17.time.time', return_value=reminder17.DUE-600):
                service = reminder17.install(app,database,lambda f:f,lambda:True,'unit-test-secret',exclude_registered)
            with database() as db:
                record = db.execute('SELECT * FROM invitation_campaigns WHERE id=?',(reminder17.CAMPAIGN,)).fetchone()
                self.assertEqual(record['due'],reminder17.DUE)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM invitation_campaign_recipients WHERE campaign_id=?',(reminder17.CAMPAIGN,)).fetchone()[0],315)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM invitation_campaign_recipients WHERE campaign_id=? AND status='excluded_registered'",(reminder17.CAMPAIGN,)).fetchone()[0],1)
                db.execute('INSERT INTO invitation_opt_outs VALUES(?,?,?)',('u3@example.com','now','unit test'))
                service['exclude'](db)
                self.assertEqual(db.execute("SELECT status FROM invitation_campaign_recipients WHERE campaign_id=? AND email='u3@example.com'",(reminder17.CAMPAIGN,)).fetchone()[0],'excluded_unsubscribed')
                db.execute('INSERT INTO registrations VALUES(?,1,0)',(json.dumps({'email':'u4@example.com'}),))
                exclude_registered(db,reminder17.CAMPAIGN,due_only=False)
                self.assertEqual(db.execute("SELECT status FROM invitation_campaign_recipients WHERE campaign_id=? AND email='u4@example.com'",(reminder17.CAMPAIGN,)).fetchone()[0],'excluded_registered')
            row = dict(id=reminder17.CAMPAIGN,email='u2@example.com',subject=reminder17.SUBJECT,html=record['html'])
            mail = service['message'](row)
            body = mail.get_body(preferencelist=('html',)).get_content()
            self.assertIn('4 inscrits',body)
            self.assertIn('width:4%',body)
            self.assertNotIn('__BNI_',body)
            self.assertIn('BNI_logo.png',body)
            self.assertEqual(mail['From'],'hub@bim-soignies.be')
            self.assertEqual(mail['To'],'u2@example.com')
            self.assertIn('4 inscrits',mail.get_body(preferencelist=('plain',)).get_content())
            self.assertEqual(mail['Message-ID'],service['message'](row)['Message-ID'])
            from urllib.parse import urlsplit
            url = urlsplit(str(mail['List-Unsubscribe']).strip('<>'))
            path = url.path + '?' + url.query
            client = app.test_client()
            self.assertEqual(client.get(path).status_code,200)
            with database() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM invitation_opt_outs').fetchone()[0],1)
            self.assertEqual(client.post(path).status_code,200)
            self.assertEqual(client.get('/invitations/retrait?email=u2@example.com&token=invalid').status_code,403)
            with database() as db:
                self.assertEqual(db.execute("SELECT status FROM invitation_campaign_recipients WHERE campaign_id=? AND email='u2@example.com'",(reminder17.CAMPAIGN,)).fetchone()[0],'excluded_unsubscribed')
                self.assertEqual(db.execute("SELECT COUNT(*) FROM invitation_campaign_recipients WHERE campaign_id=? AND status='accepted_by_smtp'",(reminder17.SOURCE,)).fetchone()[0],315)
            second_app = Flask('reminder17-repeat', static_folder=str(Path(__file__).parent / 'static'))
            with patch('reminder17.time.time', return_value=reminder17.DUE-500):
                reminder17.install(second_app,database,lambda f:f,lambda:True,'unit-test-secret',exclude_registered)
            with database() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM invitation_campaign_recipients WHERE campaign_id=?',(reminder17.CAMPAIGN,)).fetchone()[0],315)

    def test_gauge_bounds(self):
        template='__BNI_REGISTERED__ / __BNI_PERCENT__ / __BNI_REMAINING__'
        self.assertEqual(reminder17.render_gauge(template,120),'120 / 100 / 0')
        self.assertEqual(reminder17.render_gauge(template,-2),'0 / 0 / 100')


if __name__ == '__main__':
    unittest.main()
