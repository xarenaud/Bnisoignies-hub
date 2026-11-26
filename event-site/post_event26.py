"""Registered-attendee follow-up, private PDF directory, and membership enquiries."""
import os,reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import base64,hashlib,hmac,io,json,re,smtplib,time,unicodedata
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate
from html import escape
from threading import Thread
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from flask import Response,jsonify,request
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
from reminder17 import PlainMail
pdfmetrics.registerFont(TTFont('BNI',os.path.join(os.path.dirname(reportlab.__file__),'fonts','Vera.ttf')))
pdfmetrics.registerFont(TTFont('BNI-Bold',os.path.join(os.path.dirname(reportlab.__file__),'fonts','VeraBd.ttf')))
ID='inter-bni-suite-20261126-1200'
DUE=datetime(2026,11,26,12,0,tzinfo=ZoneInfo('Europe/Brussels')).timestamp()
SUBJECT='Après l’Inter-BNI : vos contacts et nos prochains rendez-vous'
PDF_NAME='Inter-BNI_26-11-2026_Repertoire_des_inscrits.pdf'
ORIGINS={'https://www.bim-soignies.be','https://bim-soignies.be'}
EMAIL=re.compile(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+')
LOGO_B64='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'
def now_iso():return datetime.now(ZoneInfo('Europe/Brussels')).isoformat()
def normalize(value):return ''.join(c for c in unicodedata.normalize('NFD',str(value).casefold()) if c.isalnum())
def directory(db,companies):
    people={}
    for row in db.execute('SELECT payload FROM registrations WHERE is_test=0 ORDER BY id'):
        p=json.loads(row['payload'])
        for index,g in enumerate([p]+p.get('guests',[])):
            first=str(g.get('firstName','')).strip();last=str(g.get('lastName','')).strip()
            key=normalize(first+' '+last)
            if not key:continue
            entry=dict(firstName=first,lastName=last,company=str(companies.get(key) or g.get('company') or '').strip(),
                email=str(g.get('email','')).strip().lower(),phone=str(g.get('phone','')).strip(),
                group=str(g.get('group') or p.get('group') or '').strip(),principal=index==0)
            old=people.get(key)
            if old is None:people[key]=entry
            else:
                if entry['principal'] and not old['principal']:
                    for k in ['firstName','lastName','group']:
                        if entry[k]:old[k]=entry[k]
                    old['principal']=True
                for k in ['company','email','phone']:
                    if not old[k] and entry[k]:old[k]=entry[k]
    return sorted(people.values(),key=lambda p:(normalize(p['lastName']),normalize(p['firstName'])))
def make_pdf(people):
    buf=io.BytesIO();size=landscape(A4);ink=colors.HexColor('#24303d');red=colors.HexColor('#cf2030')
    doc=SimpleDocTemplate(buf,pagesize=size,leftMargin=32,rightMargin=32,topMargin=48,bottomMargin=42,
        title='Inter-BNI Soignies - Répertoire des inscrits',author='BNI Soignies BIM')
    body=ParagraphStyle('body',fontName='BNI',fontSize=8.2,leading=10.7,textColor=ink)
    white=ParagraphStyle('white',parent=body,fontName='BNI-Bold',textColor=colors.white)
    title=ParagraphStyle('title',fontName='BNI-Bold',fontSize=19,leading=24,textColor=red)
    sub=ParagraphStyle('sub',fontName='BNI',fontSize=10,leading=14,textColor=ink)
    flow=[Paragraph('Répertoire des inscrits - Inter-BNI Soignies',title),Spacer(1,5),
        Paragraph('26 novembre 2026 | '+str(len(people))+' personnes distinctes | Ford Steveny Soignies',sub),Spacer(1,14)]
    rows=[[Paragraph(v,white) for v in ['Nom','Prénom','Société','Email','Téléphone','Groupe BNI']]]
    for p in people:
        values=[p['lastName'],p['firstName'],p['company'] or 'Non renseignée',p['email'] or 'Non renseigné',p['phone'] or 'Non renseigné',p['group'] or 'Non renseigné']
        rows.append([Paragraph(escape(v),body) for v in values])
    table=Table(rows,colWidths=[100,90,150,190,100,147],repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),red),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f2f4f5')]),('LINEBELOW',(0,0),(-1,0),.5,red)]))
    flow.append(table)
    def page(c,doc):
        c.setFillColor(red);c.rect(0,size[1]-12,size[0],12,fill=1,stroke=0)
        c.setFillColor(ink);c.setFont('BNI-Bold',9);c.drawString(32,size[1]-31,'BNI SOIGNIES BIM')
        c.setFont('BNI',7);c.drawString(32,24,'Coordonnées renseignées lors de l’inscription. Les informations absentes ne sont pas reconstituées.')
        c.drawRightString(size[0]-32,24,'Page '+str(doc.page))
    doc.build(flow,onFirstPage=page,onLaterPages=page)
    return buf.getvalue()
def payment_details(db,email):
    """Only the booking payer is reminded; a guest never inherits the payer's debt."""
    return [dict(r) for r in db.execute("""SELECT r.reference,r.total FROM registrations r
        LEFT JOIN expense_notes n USING(reference)
        WHERE r.is_test=0 AND r.total>0
        AND lower(trim(COALESCE(json_extract(r.payload,'$.email'),'')))=?
        AND trim(COALESCE(n.paid_at,''))='' ORDER BY r.id""",(email,))]
def payment_html(html,details):
    if not details:return html
    amount=sum(float(r['total']) for r in details)
    formatted=f'{amount:.2f}'.replace('.',',')
    references=' / '.join(str(r['reference']) for r in details)
    block=('<div style="margin:26px 0;padding:20px;background:#fff3f4;border-left:4px solid #cf2030;">'
        '<h2 style="margin:0 0 10px;font-family:Georgia,serif;font-size:24px;color:#19212c;">Un petit point sur votre règlement.</h2>'
        '<p>Sauf croisement avec votre paiement, le règlement de votre inscription reste à enregistrer. '
        'Merci de verser <strong>'+formatted+' €</strong> sur le compte <strong>BNI SOIGNIES : BE16 1431 1380 7474</strong>, '
        'en indiquant la communication <strong>'+escape(references)+'</strong>.</p>'
        '<p style="margin-bottom:0;">Vous avez déjà payé, par virement ou sur place ? Merci ! '
        'Ne tenez pas compte de ce rappel : notre suivi doit simplement vous rattraper.</p></div>')
    anchor='<p>Au plaisir de vous retrouver,'
    if anchor in html:return html.replace(anchor,block+anchor,1)
    return html.replace('</body>',block+'</body>',1)
def smtp_status(error):return 'failed' if isinstance(error,(smtplib.SMTPRecipientsRefused,smtplib.SMTPSenderRefused,smtplib.SMTPAuthenticationError)) else 'unknown'
def build_message(email,html,pdf,subject,tag,rate_secret):
    token=hmac.new(rate_secret.encode(),('invitation-opt-out:'+email).encode(),hashlib.sha256).hexdigest()
    url='https://event.bim-soignies.be/invitations/retrait?'+urlencode(dict(email=email,token=token))
    html=html.replace('{{unsubscribe_url}}',escape(url,quote=True))
    parser=PlainMail();parser.feed(html);m=EmailMessage()
    m['Subject']=subject;m['From']='hub@bim-soignies.be';m['To']=email;m['Reply-To']='event@bim-soignies.be';m['Date']=formatdate(localtime=False)
    m['Message-ID']='<'+tag+'.'+hashlib.sha256(email.encode()).hexdigest()[:20]+'@event.bim-soignies.be>'
    m['List-Unsubscribe']='<'+url+'>';m.set_content(parser.text());m.add_alternative(html,subtype='html')
    m.get_payload()[-1].add_related(base64.b64decode(LOGO_B64),maintype='image',subtype='png',cid='<bni-logo-20261126>',disposition='inline')
    m.add_attachment(pdf,maintype='application',subtype='pdf',filename=PDF_NAME)
    return m

def install(app,database,admin_required,same_origin,send,rate_secret,start_worker=True):
    with database() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS post_event_mailings(id TEXT PRIMARY KEY,due REAL,html TEXT,companies TEXT,enabled INTEGER DEFAULT 0,finalized INTEGER DEFAULT 0,pdf BLOB,records TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS post_event_recipients(mailing_id TEXT,email TEXT,status TEXT,claimed_at REAL,sent_at TEXT,error TEXT,PRIMARY KEY(mailing_id,email));
        CREATE TABLE IF NOT EXISTS post_event_tests(request_id TEXT PRIMARY KEY,status TEXT,sent_at TEXT,error TEXT);
        CREATE TABLE IF NOT EXISTS membership_interests(request_id TEXT PRIMARY KEY,payload TEXT,created_at TEXT,status TEXT DEFAULT 'pending',claimed_at REAL,sent_at TEXT,error TEXT);
        CREATE TABLE IF NOT EXISTS membership_interest_rate(address_hash TEXT,window INTEGER,count INTEGER,PRIMARY KEY(address_hash,window));''')
    with database() as db:
        if 'variant' not in {r['name'] for r in db.execute('PRAGMA table_info(post_event_recipients)')}:
            db.execute('ALTER TABLE post_event_recipients ADD COLUMN variant TEXT')
    def configured():
        with database() as db:return db.execute('SELECT * FROM post_event_mailings WHERE id=?',(ID,)).fetchone()
    def status():
        with database() as db:
            job=db.execute('SELECT * FROM post_event_mailings WHERE id=?',(ID,)).fetchone()
            if not job:return dict(id=ID,configured=False,enabled=False)
            counts={r['status']:r['n'] for r in db.execute('SELECT status,COUNT(*) n FROM post_event_recipients WHERE mailing_id=? GROUP BY status',(ID,))}
            records=json.loads(job['records']) if job['records'] else directory(db,json.loads(job['companies']))
            emails={p['email'] for p in records if EMAIL.fullmatch(p['email'])}
            excluded={r[0] for r in db.execute('SELECT email FROM invitation_opt_outs')} if db.execute("SELECT 1 FROM sqlite_master WHERE name='invitation_opt_outs'").fetchone() else set()
            pending_addresses=emails-excluded if not job['finalized'] else {r['email'] for r in db.execute("SELECT email FROM post_event_recipients WHERE mailing_id=? AND status='pending'",(ID,))}-excluded
            payment_pending=sum(bool(payment_details(db,e)) for e in pending_addresses)
            variants={r['variant']:r['n'] for r in db.execute("SELECT variant,COUNT(*) n FROM post_event_recipients WHERE mailing_id=? AND variant IS NOT NULL GROUP BY variant",(ID,))}
            return dict(id=ID,configured=True,enabled=bool(job['enabled']),state='scheduled' if job['enabled'] else 'awaiting_validation',scheduledFor=datetime.fromtimestamp(job['due'],ZoneInfo('Europe/Brussels')).isoformat(),
                paymentRemindersPending=payment_pending,paymentCheckedAtSend=True,paymentVariants=variants,finalized=bool(job['finalized']),people=len(records),addresses=len(emails),eligibleAddresses=len(emails-excluded),excluded_unsubscribed=len(emails&excluded),counts=counts,
                missingEmail=sum(not p['email'] for p in records),missingPhone=sum(not p['phone'] for p in records),missingCompany=sum(not p['company'] for p in records))
    @app.get('/api/admin/post-event-20261126')
    @admin_required
    def post_event_status():return jsonify(status())
    @app.post('/api/admin/post-event-20261126/configure')
    @admin_required
    def configure():
        if not same_origin():return jsonify(error='Origine non autorisée.'),403
        body=request.get_json(silent=True)
        if not isinstance(body,dict):return jsonify(error='Configuration invalide.'),422
        html=body.get('html','');companies=body.get('companies',{})
        if not isinstance(html,str) or not 200<len(html)<30000 or not isinstance(companies,dict) or len(companies)>200:return jsonify(error='Configuration invalide.'),422
        if not all(isinstance(k,str) and isinstance(v,str) and len(k)<250 and len(v)<250 for k,v in companies.items()):return jsonify(error='Sociétés invalides.'),422
        with database() as db:
            old=db.execute('SELECT finalized FROM post_event_mailings WHERE id=?',(ID,)).fetchone()
            if old and old['finalized']:return jsonify(error='Envoi déjà pris en charge ; aucune modification.'),409
            db.execute('INSERT INTO post_event_mailings(id,due,html,companies,enabled,created_at) VALUES(?,?,?,?,0,?) ON CONFLICT(id) DO UPDATE SET html=excluded.html,companies=excluded.companies',
                (ID,DUE,html,json.dumps(companies,ensure_ascii=False),now_iso()))
        return jsonify(status())
    @app.post('/api/admin/post-event-20261126/approve')
    @admin_required
    def approve():
        if not same_origin():return jsonify(error='Origine non autorisée.'),403
        if not configured():return jsonify(error='Mail non configuré.'),409
        with database() as db:db.execute('UPDATE post_event_mailings SET enabled=1 WHERE id=?',(ID,))
        return jsonify(status())
    @app.get('/api/admin/post-event-20261126/directory.pdf')
    @admin_required
    def directory_pdf():
        job=configured()
        if not job:return jsonify(error='Mail non configuré.'),409
        with database() as db:pdf=make_pdf(directory(db,json.loads(job['companies'])))
        return Response(pdf,mimetype='application/pdf',headers={'Content-Disposition':'attachment; filename="'+PDF_NAME+'"','Cache-Control':'no-store'})
    @app.post('/api/admin/post-event-20261126/test')
    @admin_required
    def test_mail():
        if not same_origin():return jsonify(error='Origine non autorisée.'),403
        job=configured()
        if not job:return jsonify(error='Mail non configuré.'),409
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify(error='Données invalides.'),422
        rid=str(data.get('requestId',''))
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',rid):return jsonify(error='Identifiant de test requis.'),422
        with database() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT status,sent_at,error FROM post_event_tests WHERE request_id=?',(rid,)).fetchone()
            if old:return jsonify(**dict(old),alreadyProcessed=True)
            db.execute('INSERT INTO post_event_tests(request_id,status) VALUES(?,?)',(rid,'sending'))
            records=directory(db,json.loads(job['companies']))
        pdf=make_pdf(records);result='accepted_by_smtp';error=None
        try:send(build_message('xavier@cx-com.be',job['html'],pdf,'[TEST] '+SUBJECT,rid,rate_secret))
        except Exception as e:result=smtp_status(e);error=type(e).__name__
        with database() as db:db.execute('UPDATE post_event_tests SET status=?,sent_at=?,error=? WHERE request_id=?',(result,now_iso() if result=='accepted_by_smtp' else None,error,rid))
        return jsonify(status=result,error=error,to='xavier@cx-com.be',people=len(records),attachment=PDF_NAME)
    def deliver():
        current=time.time()
        with database() as db:
            db.execute('BEGIN IMMEDIATE');job=db.execute('SELECT * FROM post_event_mailings WHERE id=?',(ID,)).fetchone()
            if not job or not job['enabled'] or current<job['due']:return False
            if not job['finalized']:
                records=directory(db,json.loads(job['companies']));pdf=make_pdf(records)
                addresses=sorted({p['email'] for p in records if EMAIL.fullmatch(p['email'])})
                db.executemany('INSERT OR IGNORE INTO post_event_recipients(mailing_id,email,status,claimed_at,sent_at,error) VALUES(?,?,?,NULL,NULL,NULL)',[(ID,e,'pending') for e in addresses])
                db.execute('UPDATE post_event_mailings SET finalized=1,pdf=?,records=? WHERE id=?',(pdf,json.dumps(records,ensure_ascii=False),ID))
                job=db.execute('SELECT * FROM post_event_mailings WHERE id=?',(ID,)).fetchone()
            db.execute("UPDATE post_event_recipients SET status='unknown',error='DeliveryInterrupted' WHERE mailing_id=? AND status='sending' AND claimed_at<?",(ID,current-300))
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='invitation_opt_outs'").fetchone():
                db.execute("UPDATE post_event_recipients SET status='excluded_unsubscribed',error=NULL WHERE mailing_id=? AND status='pending' AND email IN (SELECT email FROM invitation_opt_outs)",(ID,))
            row=db.execute("SELECT email FROM post_event_recipients WHERE mailing_id=? AND status='pending' ORDER BY email LIMIT 1",(ID,)).fetchone()
            if not row:return False
            email=row['email'];details=payment_details(db,email);variant='payment_reminder' if details else 'information_only'
            html=payment_html(job['html'],details)
            db.execute("UPDATE post_event_recipients SET status='sending',claimed_at=?,variant=? WHERE mailing_id=? AND email=?",(current,variant,ID,email))
        result='accepted_by_smtp';error=None
        try:send(build_message(email,html,bytes(job['pdf']),SUBJECT,ID,rate_secret))
        except Exception as e:result=smtp_status(e);error=type(e).__name__
        with database() as db:db.execute('UPDATE post_event_recipients SET status=?,sent_at=?,error=? WHERE mailing_id=? AND email=?',(result,now_iso() if result=='accepted_by_smtp' else None,error,ID,email))
        app.logger.info('POST_EVENT_DELIVERY %s',json.dumps(dict(id=ID,status=result,variant=variant,error=error)))
        return True
    @app.route('/api/public/membership-interest',methods=['POST','OPTIONS'])
    def membership_interest():
        origin=request.headers.get('Origin','')
        if origin not in ORIGINS:return jsonify(error='Origine non autorisée.'),403
        if request.method=='OPTIONS':return Response(status=204)
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify(error='Données invalides.'),422
        rid=str(data.get('requestId',''))
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',rid):return jsonify(error='Veuillez actualiser le formulaire.'),422
        limits={'firstName':100,'lastName':100,'company':160,'activity':160,'email':254,'phone':50,'message':2000}
        clean={}
        for key,limit in limits.items():
            value=data.get(key,'')
            if not isinstance(value,str) or len(value)>limit:return jsonify(error='Vérifiez les champs du formulaire.'),422
            clean[key]=value.strip()
        if data.get('website'):return jsonify(ok=True)
        if not all(clean[k] for k in ['firstName','lastName','company','activity']) or not EMAIL.fullmatch(clean['email']) or data.get('consent') is not True:return jsonify(error='Complétez les champs obligatoires et autorisez le suivi de votre demande.'),422
        if any('\r' in clean[k] or '\n' in clean[k] for k in ['firstName','lastName','email']):return jsonify(error='Vérifiez vos coordonnées.'),422
        address=request.headers.get('X-Real-IP',request.remote_addr or '');digest=hmac.new(rate_secret.encode(),address.encode(),hashlib.sha256).hexdigest();window=int(time.time())//3600
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM membership_interests WHERE request_id=?',(rid,)).fetchone():return jsonify(ok=True)
            previous=db.execute('SELECT count FROM membership_interest_rate WHERE address_hash=? AND window=?',(digest,window)).fetchone()
            if previous and previous['count']>=6:return jsonify(error='Trop de demandes. Merci de réessayer plus tard ou de nous écrire.'),429
            db.execute('DELETE FROM membership_interest_rate WHERE window<?',(window-1,))
            db.execute('INSERT INTO membership_interest_rate VALUES(?,?,1) ON CONFLICT(address_hash,window) DO UPDATE SET count=count+1',(digest,window))
            clean['consentAt']=now_iso();db.execute('INSERT INTO membership_interests(request_id,payload,created_at) VALUES(?,?,?)',(rid,json.dumps(clean,ensure_ascii=False),now_iso()))
        return jsonify(ok=True),201
    @app.after_request
    def membership_cors(response):
        if request.path=='/api/public/membership-interest' and request.headers.get('Origin') in ORIGINS:
            response.headers['Access-Control-Allow-Origin']=request.headers['Origin'];response.headers['Vary']='Origin'
            response.headers['Access-Control-Allow-Methods']='POST, OPTIONS';response.headers['Access-Control-Allow-Headers']='Content-Type'
        return response
    @app.get('/api/admin/membership-interests')
    @admin_required
    def membership_interest_list():
        with database() as db:rows=db.execute('SELECT request_id,payload,created_at,status,sent_at,error FROM membership_interests ORDER BY created_at DESC').fetchall()
        return jsonify(items=[dict(r) for r in rows])
    def notify_interest():
        with database() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute("SELECT * FROM membership_interests WHERE status='pending' ORDER BY created_at LIMIT 1").fetchone()
            if not row:return False
            db.execute("UPDATE membership_interests SET status='sending',claimed_at=? WHERE request_id=?",(time.time(),row['request_id']))
        p=json.loads(row['payload']);m=EmailMessage();m['From']='hub@bim-soignies.be';m['To']='hub@bim-soignies.be';m['Reply-To']=p['email'];m['Subject']='Demande pour rejoindre BNI Soignies - '+p['firstName']+' '+p['lastName'];m['Message-ID']='<membership-'+row['request_id']+'@event.bim-soignies.be>'
        m.set_content('Nouvelle demande pour rejoindre le groupe BNI Soignies BIM.\n\n'+'\n'.join(k+' : '+p[k] for k in ['firstName','lastName','company','activity','email','phone','message','consentAt']))
        result='accepted_by_smtp';error=None
        try:send(m)
        except Exception as e:result=smtp_status(e);error=type(e).__name__
        with database() as db:db.execute('UPDATE membership_interests SET status=?,sent_at=?,error=? WHERE request_id=?',(result,now_iso() if result=='accepted_by_smtp' else None,error,row['request_id']))
        return True
    if start_worker:
        def run():
            while True:
                try:deliver();notify_interest()
                except Exception as e:app.logger.error('POST_EVENT_WORKER_ERROR %s',type(e).__name__)
                time.sleep(2)
        Thread(target=run,daemon=True,name='post-event-and-membership').start()
    return dict(status=status,deliver=deliver,directory=directory,notify_interest=notify_interest)
