"""Approved registered-attendee information mailing, November 24 at 13:00."""
import hashlib,json,re,smtplib,time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from threading import Thread
from zoneinfo import ZoneInfo
from flask import jsonify
from reminder17 import PlainMail

ID='inter-bni-inscrits-20261124-1300'
DUE=datetime(2026,11,24,13,0,tzinfo=ZoneInfo('Europe/Brussels')).timestamp()
SUBJECT='Inter-BNI jeudi : votre slide, votre arrivée et les informations pratiques'
def install(app,database,admin_required,send,start_worker=True,mailing_id=ID,due_at=DUE,status_path='/api/admin/attendee-information-20261124'):
    ID=mailing_id
    DUE=due_at
    def audience(db):
        emails=set()
        for row in db.execute('SELECT payload FROM registrations WHERE is_test=0'):
            p=json.loads(row['payload'])
            for entry in [p]+p.get('guests',[]):
                email=entry.get('email','').strip().lower()
                if re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',email):emails.add(email)
        db.executemany('INSERT OR IGNORE INTO attendee_information_recipients(mailing_id,email,status) VALUES(?,?,?)',[(ID,e,'pending') for e in sorted(emails)])
        return len(emails)

    with database() as db:
        db.executescript("""CREATE TABLE IF NOT EXISTS attendee_information_mailings(
            id TEXT PRIMARY KEY,due REAL,subject TEXT,html_unpaid TEXT,html_paid TEXT,finalized INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS attendee_information_recipients(
            mailing_id TEXT,email TEXT,status TEXT,claimed_at REAL,sent_at TEXT,variant TEXT,error TEXT,
            PRIMARY KEY(mailing_id,email));""")
        unpaid=(Path(app.static_folder)/'mailing-inter-bni-arrivee-v2.html').read_text()
        paid=(Path(app.static_folder)/'mailing-inter-bni-arrivee-reglee.html').read_text()
        if 'Sauf croisement' not in unpaid or 'Sauf croisement' in paid:
            raise RuntimeError('Approved payment variants invalid')
        db.execute('INSERT OR IGNORE INTO attendee_information_mailings(id,due,subject,html_unpaid,html_paid) VALUES(?,?,?,?,?)',(ID,DUE,SUBJECT,unpaid,paid))
        if not db.execute('SELECT finalized FROM attendee_information_mailings WHERE id=?',(ID,)).fetchone()[0]:
            audience(db)

    def needs_payment(db,email):
        return bool(db.execute("""SELECT 1 FROM registrations r LEFT JOIN expense_notes n USING(reference)
            WHERE r.is_test=0 AND lower(trim(COALESCE(json_extract(r.payload,'$.email'),'')))=?
            AND (n.paid_at IS NULL OR n.paid_at='') LIMIT 1""",(email,)).fetchone())

    def summary():
        with database() as db:
            job=db.execute('SELECT * FROM attendee_information_mailings WHERE id=?',(ID,)).fetchone()
            counts={r['status']:r['n'] for r in db.execute('SELECT status,COUNT(*) n FROM attendee_information_recipients WHERE mailing_id=? GROUP BY status',(ID,))}
            pending=[r['email'] for r in db.execute("SELECT email FROM attendee_information_recipients WHERE mailing_id=? AND status='pending'",(ID,))]
            with_reminder=sum(needs_payment(db,e) for e in pending)
            regs=db.execute('SELECT COUNT(*),COALESCE(SUM(count),0) FROM registrations WHERE is_test=0').fetchone()
        return dict(id=ID,scheduledFor=datetime.fromtimestamp(job['due'],ZoneInfo('Europe/Brussels')).isoformat(),
            subject=job['subject'],counts=counts,total=sum(counts.values()),paymentRemindersPending=with_reminder,
            registrations=regs[0],participants=regs[1],audienceFinalized=bool(job['finalized']))

    def attendee_information_status():
        return jsonify(summary())
    app.add_url_rule(status_path,endpoint='attendee_information_status_'+ID,
        view_func=admin_required(attendee_information_status),methods=['GET'])

    def deliver():
        now=time.time()
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            job=db.execute('SELECT * FROM attendee_information_mailings WHERE id=?',(ID,)).fetchone()
            if now<job['due']:return False
            if not job['finalized']:
                audience(db)
                db.execute('UPDATE attendee_information_mailings SET finalized=1 WHERE id=?',(ID,))
            db.execute("UPDATE attendee_information_recipients SET status='unknown',error='DeliveryInterrupted' WHERE mailing_id=? AND status='sending' AND claimed_at<?",(ID,now-300))
            row=db.execute("SELECT email FROM attendee_information_recipients WHERE mailing_id=? AND status='pending' ORDER BY email LIMIT 1",(ID,)).fetchone()
            if not row:return False
            email=row['email']
            variant='payment_reminder' if needs_payment(db,email) else 'information_only'
            html=job['html_unpaid'] if variant=='payment_reminder' else job['html_paid']
            db.execute("UPDATE attendee_information_recipients SET status='sending',claimed_at=?,variant=? WHERE mailing_id=? AND email=?",(now,variant,ID,email))
        status='accepted_by_smtp';error_kind=None
        try:
            parser=PlainMail();parser.feed(html)
            message=EmailMessage()
            message['Subject']=job['subject'];message['From']='hub@bim-soignies.be';message['To']=email
            message['Reply-To']='event@bim-soignies.be';message['Date']=formatdate(localtime=False)
            message['Message-ID']='<'+ID+'.'+hashlib.sha256(email.encode()).hexdigest()[:20]+'@event.bim-soignies.be>'
            message.set_content(parser.text());message.add_alternative(html,subtype='html')
            message.get_payload()[-1].add_related((Path(app.static_folder)/'plan-acces-inter-bni.png').read_bytes(),
                maintype='image',subtype='png',cid='<plan-acces-inter-bni>',
                filename='Plan-acces-Inter-BNI-26-novembre.png',disposition='inline')
            send(message)
        except Exception as error:
            status='failed' if isinstance(error,(smtplib.SMTPRecipientsRefused,smtplib.SMTPSenderRefused,smtplib.SMTPAuthenticationError)) else 'unknown'
            error_kind=type(error).__name__
        with database() as db:
            db.execute('UPDATE attendee_information_recipients SET status=?,sent_at=?,error=? WHERE mailing_id=? AND email=?',
                (status,datetime.now(ZoneInfo('Europe/Brussels')).isoformat() if status=='accepted_by_smtp' else None,error_kind,ID,email))
        app.logger.info('ATTENDEE_INFORMATION_DELIVERY %s',json.dumps(dict(id=ID,status=status,variant=variant,error=error_kind)))
        return True

    app.logger.warning('ATTENDEE_INFORMATION_SCHEDULE_VERIFIED %s',json.dumps(summary(),ensure_ascii=False))
    if start_worker:
        def run():
            while True:
                try:deliver()
                except Exception as error:app.logger.error('ATTENDEE_INFORMATION_WORKER_ERROR %s',type(error).__name__)
                time.sleep(2)
        Thread(target=run,daemon=True,name='approved-attendee-information').start()
    return dict(summary=summary,deliver=deliver)
