"""Send only the two expressly requested arrival-email review copies, once."""
import json
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from threading import Thread
from zoneinfo import ZoneInfo
from reminder17 import PlainMail

RECIPIENTS=('xavier@cx-com.be',)
SUBJECT='[TEST V5] Inter-BNI jeudi : slide, parking et règlement'

def build_message(recipient,request_id,html,plan):
    parser=PlainMail()
    parser.feed(html)
    message=EmailMessage()
    message['Subject']=SUBJECT
    message['From']='hub@bim-soignies.be'
    message['To']=recipient
    message['Reply-To']='event@bim-soignies.be'
    message['Date']=formatdate(localtime=False)
    message['Message-ID']='<'+request_id+'@event.bim-soignies.be>'
    message.set_content(parser.text())
    message.add_alternative(html,subtype='html')
    message.get_payload()[-1].add_related(plan,maintype='image',subtype='png',
        cid='<plan-acces-inter-bni>',filename='Plan-acces-Inter-BNI-26-novembre.png',disposition='inline')
    return message

def install(app,database,send):
    def run():
        # The explicit test request is dated November 24; never initiate it on a later day.
        if datetime.now(ZoneInfo('Europe/Brussels')).date().isoformat()!='2026-11-24':
            return
        html=(Path(app.static_folder)/'mailing-inter-bni-arrivee-v2.html').read_text()
        plan=(Path(app.static_folder)/'plan-acces-inter-bni.png').read_bytes()
        with database() as db:
            db.execute('CREATE TABLE IF NOT EXISTS invitation_tests (request_id TEXT PRIMARY KEY,status TEXT NOT NULL,created_at TEXT NOT NULL)')
        for i,recipient in enumerate(RECIPIENTS):
            request_id='test-arrival-v5-payment-20261124-xavier-'+str(i+1)
            with database() as db:
                db.execute('BEGIN IMMEDIATE')
                existing=db.execute('SELECT status FROM invitation_tests WHERE request_id=?',(request_id,)).fetchone()
                if existing:
                    app.logger.warning('ARRIVAL_V5_TEST_RESULT %s',json.dumps(dict(recipient=recipient,status=existing['status'],existing=True)))
                    continue
                db.execute('INSERT INTO invitation_tests VALUES(?,?,?)',(request_id,'sending',datetime.now(ZoneInfo('Europe/Brussels')).isoformat()))
            status='accepted_by_smtp'
            error_kind=None
            try:
                send(build_message(recipient,request_id,html,plan))
            except Exception as error:
                status='unknown'
                error_kind=type(error).__name__
            with database() as db:
                db.execute('UPDATE invitation_tests SET status=? WHERE request_id=?',(status,request_id))
            app.logger.warning('ARRIVAL_V5_TEST_RESULT %s',json.dumps(dict(recipient=recipient,status=status,error=error_kind)))
    Thread(target=run,daemon=True,name='arrival-two-review-tests').start()
