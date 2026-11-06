"""Organizer-only stored expense notes, payment validation and explicit email delivery."""
import hashlib
import hmac
import io
import json
import re
import threading
import time
import urllib.request
from datetime import datetime, date
from email.message import EmailMessage
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Response, abort, redirect, request

ISSUER = 'BNI SOIGNIES - BIM'
ISSUER_ADDRESS = 'Chaussée de Bruxelles 38<br/>7061 Casteau'
PURPOSE = 'participation à la rencontre Inter BNI du 26 novembre 2026 et à la présentation sur la mobilité en 2027'


def clock():
    return datetime.now(ZoneInfo('Europe/Brussels')).isoformat()


def company_lookup(vat):
    vat = re.sub(r'[^A-Za-z0-9]', '', vat).upper()
    if vat.isdigit() and len(vat) == 10:
        vat = 'BE' + vat
    if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{2,30}', vat):
        return '', '', 'Numéro à vérifier manuellement'
    req = urllib.request.Request('https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number', data=json.dumps({'countryCode': vat[:2], 'vatNumber': vat[2:]}).encode(), headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read(65536))
        if data.get('valid') is not True:
            return '', '', 'VIES : coordonnées non confirmées, à compléter'
        def clean(value):
            text = str(value or '').strip()
            return '' if text in ('---', '--', '-') else text
        name = clean(data.get('name') or data.get('traderName'))
        address = clean(data.get('address')) or '\n'.join(filter(None, [clean(data.get('traderStreet')), ' '.join(filter(None, [clean(data.get('traderPostalCode')), clean(data.get('traderCity'))]))]))
        return name[:200], address[:600], 'VIES : recherche effectuée le ' + clock()
    except Exception:
        return '', '', 'VIES indisponible : coordonnées à compléter ou recherche à relancer'


def note_pdf(registration, note, logo):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph
    p = json.loads(registration['payload'])
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=(595.28, 841.89))
    c.setTitle('Note de frais ' + registration['reference'])
    c.setAuthor(ISSUER)
    red = colors.HexColor('#cf2030')
    c.setFillColor(red); c.rect(0, 827, 595.28, 15, fill=1, stroke=0)
    # Use the original BNI logo, cropping its surrounding white canvas in memory.
    from PIL import Image, ImageChops
    img = Image.open(logo).convert('RGB')
    bounds = ImageChops.difference(img, Image.new('RGB', img.size, 'white')).getbbox()
    img = img.crop(bounds) if bounds else img
    c.drawImage(ImageReader(img), 48, 733, width=112, height=42, preserveAspectRatio=True, mask='auto')
    c.setFillColor(colors.HexColor('#16202d')); c.setFont('Helvetica-Bold', 23); c.drawString(48, 681, 'NOTE DE FRAIS')
    final = bool(note['issued_at'] and note['paid_at'] and note['company_name'] and note['company_address'])
    c.setFillColor(red); c.setFont('Helvetica-Bold', 10)
    c.drawString(48, 657, ('REÇU DE PAIEMENT' if final else 'BROUILLON - NE VAUT PAS REÇU DE PAIEMENT'))
    style = ParagraphStyle('body', fontName='Helvetica', fontSize=11, leading=17, textColor=colors.HexColor('#263442'), alignment=TA_LEFT)
    def para(text, y, width=495):
        v = Paragraph(text, style); _, h = v.wrap(width, 720)
        if y-h < 115:
            c.setFont('Helvetica',9); c.drawString(48,65,'Note de frais - '+registration['reference']+' - suite')
            c.showPage(); y=780
        v.drawOn(c, 48, y-h); return y-h-18
    y = 620
    y = para('<b>Émetteur</b><br/>' + ISSUER + '<br/>Association de fait<br/>' + ISSUER_ADDRESS, y)
    number = 'NF-' + registration['reference']
    y = para('<b>Référence :</b> ' + number + '<br/><b>Inscription :</b> ' + registration['reference'], y)
    person = escape(p['lastName'] + ' ' + p['firstName'])
    amount = str(registration['total']) + ',00 EUR'
    if final:
        wording = f'Je soussigné, {ISSUER}, association de fait, déclare avoir reçu de la part de <b>{person}</b> la somme de <b>{amount}</b> dans le cadre de sa {PURPOSE}.'
    else:
        wording = f'Document préparatoire pour <b>{person}</b>, pour un montant de <b>{amount}</b>, dans le cadre de sa {PURPOSE}. Ce brouillon ne constate aucun encaissement.'
    y = para(wording, y)
    company = escape(note['company_name'] or 'Raison sociale à compléter')
    address = escape(note['company_address'] or 'Adresse à compléter').replace('\n', '<br/>')
    y = para('Cette note de frais est établie au profit de la société :<br/><b>' + company + '</b><br/>' + address + '<br/><b>N° de TVA :</b> ' + escape(p.get('vatNumber', '')), y)
    if final:
        paid = datetime.fromisoformat(note['paid_at']).strftime('%d/%m/%Y')
        y = para('<b>Paiement reçu par virement le :</b> ' + paid + '<br/><b>Référence du virement :</b> ' + escape(note['bank_reference'] or 'Non renseignée') + '<br/><b>Date d’émission :</b> ' + datetime.fromisoformat(note['issued_at']).strftime('%d/%m/%Y'), y)
    c.setStrokeColor(colors.HexColor('#dce0e5')); c.line(48, 88, 547, 88)
    c.setFont('Helvetica', 9); c.setFillColor(colors.HexColor('#66717d'))
    c.drawString(48, 67, ISSUER + ' - Association de fait')
    c.drawString(48, 51, 'event@bim-soignies.be | ' + number)
    c.save()
    return output.getvalue()


def install(app, database, admin_required, same_origin, send_notification, admin_password, notifications_enabled):
    with database() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS expense_notes (
          reference TEXT PRIMARY KEY, company_name TEXT NOT NULL DEFAULT '', company_address TEXT NOT NULL DEFAULT '',
          lookup_status TEXT NOT NULL DEFAULT 'pending', paid_at TEXT, bank_reference TEXT NOT NULL DEFAULT '',
          issued_at TEXT, draft_pdf BLOB, final_pdf BLOB, mail_status TEXT NOT NULL DEFAULT 'not_sent',
          sent_at TEXT, last_error TEXT, claim_at REAL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS expense_audit (
          id INTEGER PRIMARY KEY, reference TEXT NOT NULL, action TEXT NOT NULL, at TEXT NOT NULL, actor TEXT NOT NULL);''')
    logo = Path(app.static_folder) / 'images' / 'bni-logo.png'

    def audit(db, ref, action):
        db.execute('INSERT INTO expense_audit(reference,action,at,actor) VALUES(?,?,?,?)', (ref, action, clock(), 'bni'))

    def ensure(ref):
        with database() as db:
            r = db.execute('SELECT * FROM registrations WHERE reference=? AND is_test=0', (ref,)).fetchone()
            if not r:
                return None
            db.execute('INSERT OR IGNORE INTO expense_notes(reference,updated_at) VALUES(?,?)', (ref, clock()))
            n = db.execute('SELECT * FROM expense_notes WHERE reference=?', (ref,)).fetchone()
        return r, n

    def save_draft(r, n):
        if json.loads(r['payload']).get('vatNumber') and not n['final_pdf']:
            b = note_pdf(r, n, logo)
            with database() as db:
                db.execute('UPDATE expense_notes SET draft_pdf=?,updated_at=? WHERE reference=? AND final_pdf IS NULL', (b,clock(),r['reference']))

    def lookup(ref):
        pair = ensure(ref)
        if not pair:
            return
        r, n = pair
        if n['final_pdf']:
            return
        vat = json.loads(r['payload']).get('vatNumber', '')
        name, address, status = company_lookup(vat)
        with database() as db:
            db.execute("UPDATE expense_notes SET company_name=CASE WHEN company_name='' THEN ? ELSE company_name END, company_address=CASE WHEN company_address='' THEN ? ELSE company_address END, lookup_status=?,updated_at=? WHERE reference=? AND final_pdf IS NULL", (name,address,status,clock(),ref))
        r, n = ensure(ref); save_draft(r, n)

    def prepare_pending():
        with database() as db:
            rows = db.execute("SELECT r.reference,r.payload FROM registrations r LEFT JOIN expense_notes n USING(reference) WHERE r.is_test=0 AND COALESCE(json_extract(r.payload,'$.vatNumber'),'')<>'' AND (n.reference IS NULL OR n.lookup_status='pending') ORDER BY r.id LIMIT 100").fetchall()
        for r in rows:
            p = json.loads(r['payload'])
            if not p.get('vatNumber'):
                continue
            pair = ensure(r['reference'])
            save_draft(*pair)
            lookup(r['reference'])

    def worker():
        while True:
            try:
                prepare_pending()
            except Exception:
                app.logger.warning('Expense note preparation temporarily unavailable')
            time.sleep(30)

    if notifications_enabled:
        threading.Thread(target=worker,daemon=True,name='expense-preparation').start()

    def token(ref, action):
        return hmac.new(admin_password.encode(), ('expense:'+ref+':'+action).encode(), hashlib.sha256).hexdigest()

    def form(ref, action, label, extra=''):
        return '<form method="post" action="/admin/inscriptions/'+ref+'/note/'+action+'"><input type="hidden" name="token" value="'+token(ref,action)+'">'+extra+'<button class="button" type="submit">'+label+'</button></form>'

    def guard(ref, action):
        if not same_origin() or not hmac.compare_digest(request.form.get('token',''),token(ref,action)):
            abort(403)

    def page(title, body):
        return Response('<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>'+escape(title)+'</title><link rel="stylesheet" href="/admin/inscriptions.css"><link rel="stylesheet" href="/admin/notes.css"></head><body><main><p class="brand">BNI SOIGNIES - BIM · ORGANISATEUR</p><h1>'+escape(title)+'</h1><p><a href="/admin/inscriptions">Retour à la liste des inscrits</a></p>'+body+'</main></body></html>',mimetype='text/html')

    @app.get('/admin/notes.css')
    @admin_required
    def note_css():
        return Response('form{margin:22px 0;max-width:720px}label{display:block;margin:16px 0}input,textarea{display:block;width:100%;padding:12px;font:inherit;margin-top:6px;border:1px solid #718096;border-radius:3px}textarea{min-height:100px}button{border:0;font:inherit;cursor:pointer}iframe{width:100%;height:650px;border:1px solid #718096}.card{background:#202b3b;padding:24px;max-width:900px}strong{color:#fff}.success{color:#9ce5bd}',mimetype='text/css')

    @app.get('/admin/inscriptions/<ref>/note')
    @admin_required
    def detail(ref):
        pair = ensure(ref)
        if not pair:
            abort(404)
        r, n = pair; p=json.loads(r['payload']);has_vat=bool(p.get('vatNumber'))
        if has_vat and not n['draft_pdf'] and not n['final_pdf']:
            save_draft(r,n);r,n=ensure(ref)
        body='<section class="card"><p><strong>'+escape(p['firstName']+' '+p['lastName'])+'</strong> · '+escape(ref)+'</p><p>'+str(r['count'])+' place(s) · <strong>'+str(r['total'])+' €</strong></p><p>Email : '+escape(p.get('email',''))+'</p><p>TVA : '+escape(p.get('vatNumber','Non renseignée'))+'</p></section>'
        if not n['paid_at']:
            body+='<h2>Paiement à vérifier</h2><p>Valide uniquement après avoir constaté la réception du montant total par virement.</p>'
            body+=form(ref,'payment','Valider le paiement reçu', '<label>Date de réception<input type="date" name="paymentDate" max="'+date.today().isoformat()+'" value="'+date.today().isoformat()+'" required></label><label>Référence du virement<input name="bankReference" maxlength="200"></label><label>Montant reçu (€)<input type="number" name="amount" min="0" step="0.01" required></label><label><input type="checkbox" name="confirmed" value="yes" required> Je confirme avoir reçu la totalité du paiement.</label>')
        else:
            body+='<p class="success">Paiement validé : '+escape(n['paid_at'])+' · '+escape(n['bank_reference'])+'</p>'
        if not has_vat:
            return page('Paiement de l’inscription',body+'<p>Aucun numéro de TVA renseigné : pas de note de frais à établir.</p>')
        body+='<h2>Coordonnées de la société</h2><p>'+escape(n['lookup_status'])+'</p>'
        if not n['final_pdf']:
            body+=form(ref,'lookup','Relancer la recherche par TVA')
            body+=form(ref,'company','Enregistrer les coordonnées et préparer le PDF','<label>Raison sociale<input name="companyName" value="'+escape(n['company_name'],quote=True)+'" maxlength="200" required></label><label>Adresse complète<textarea name="companyAddress" maxlength="600" required>'+escape(n['company_address'])+'</textarea></label>')
        else:
            body+='<p>'+escape(n['company_name'])+'<br>'+escape(n['company_address']).replace('\n','<br>')+'</p><p>Document définitif conservé, émis le '+escape(n['issued_at'])+'.</p>'
        if n['paid_at'] and n['company_name'] and n['company_address'] and not n['final_pdf']:
            body+=form(ref,'issue','Générer la note définitive')
        url='/admin/inscriptions/'+ref+'/note.pdf'
        body+='<p><a class="button" href="'+url+'" target="_blank" rel="noopener">Télécharger '+('la note définitive' if n['final_pdf'] else 'le brouillon')+' (PDF)</a></p>'
        if n['final_pdf']:
            body+='<h2>Envoi au participant</h2><p>Destinataire : '+escape(p.get('email',''))+'</p>'
            if n['mail_status']=='not_sent':
                body+=form(ref,'send','Envoyer la note de frais par email')
            else:
                body+='<p>État : '+escape(n['mail_status'])+' · '+escape(n['sent_at'] or '')+'</p>'
                if n['last_error']:body+='<p>Incident : '+escape(n['last_error'])+'. Aucun renvoi automatique pour éviter un doublon.</p>'
        with database() as db:
            history=db.execute('SELECT action,at FROM expense_audit WHERE reference=? ORDER BY id DESC',(ref,)).fetchall()
        body+='<h2>Historique</h2><ul>'+''.join('<li>'+escape(x['at'])+' — '+escape(x['action'])+'</li>' for x in history)+'</ul>'
        return page('Paiement et note de frais',body)

    @app.post('/admin/inscriptions/<ref>/note/<action>')
    @admin_required
    def action(ref,action):
        guard(ref,action);pair=ensure(ref)
        if not pair:abort(404)
        r,n=pair;p=json.loads(r['payload']);back='/admin/inscriptions/'+ref+'/note'
        if action=='payment':
            from decimal import Decimal, InvalidOperation
            try:
                amount=Decimal(request.form.get('amount',''))
                paid=date.fromisoformat(request.form.get('paymentDate',''))
            except (ValueError,InvalidOperation):abort(422)
            if amount!=Decimal(r['total']) or paid>date.today() or request.form.get('confirmed')!='yes':
                return page('Paiement non validé','<p>Le montant doit correspondre au total dû et la date ne peut pas être future.</p><p><a href="'+back+'">Revenir au dossier</a></p>'),422
            with database() as db:
                db.execute('BEGIN IMMEDIATE')
                changed=db.execute('UPDATE expense_notes SET paid_at=?,bank_reference=?,updated_at=? WHERE reference=? AND paid_at IS NULL',(paid.isoformat(),request.form.get('bankReference','')[:200],clock(),ref))
                if changed.rowcount:audit(db,ref,'Paiement total validé : '+str(r['total'])+' EUR')
            r,n=ensure(ref)
            if p.get('vatNumber') and n['company_name'] and n['company_address']:issue(ref)
        elif action=='company':
            name=request.form.get('companyName','').strip();address=request.form.get('companyAddress','').strip()
            if not 1<=len(name)<=200 or not 1<=len(address)<=600:abort(422)
            with database() as db:
                db.execute('BEGIN IMMEDIATE')
                changed=db.execute('UPDATE expense_notes SET company_name=?,company_address=?,lookup_status=?,updated_at=? WHERE reference=? AND final_pdf IS NULL',(name,address,'Coordonnées confirmées par l’organisateur',clock(),ref))
                if not changed.rowcount:abort(409)
                audit(db,ref,'Coordonnées de la société enregistrées')
            r,n=ensure(ref);save_draft(r,n)
            if n['paid_at']:issue(ref)
        elif action=='lookup':lookup(ref)
        elif action=='issue':issue(ref)
        elif action=='send':
            with database() as db:
                db.execute('BEGIN IMMEDIATE')
                n=db.execute('SELECT * FROM expense_notes WHERE reference=?',(ref,)).fetchone()
                if not n['paid_at'] or not n['final_pdf']:abort(409)
                if n['mail_status']!='not_sent':return redirect(back,303)
                db.execute("UPDATE expense_notes SET mail_status='sending',claim_at=? WHERE reference=?",(time.time(),ref));audit(db,ref,'Envoi du PDF demandé')
            message=EmailMessage();message['Subject']='Votre note de frais - Inter BNI - '+ref
            message['From']='hub@bim-soignies.be';message['To']=p['email'];message['Reply-To']='event@bim-soignies.be'
            from email.utils import formatdate
            message['Date']=formatdate(localtime=False);message['Message-ID']='<expense.'+ref+'@event.bim-soignies.be>'
            message.set_content('Bonjour '+p['firstName']+',\n\nVous trouverez en pièce jointe votre note de frais, établie après validation de votre paiement pour la rencontre Inter BNI du 26 novembre 2026.\n\nBNI SOIGNIES - BIM\nAssociation de fait\nChaussée de Bruxelles 38, 7061 Casteau\nevent@bim-soignies.be')
            message.add_attachment(bytes(n['final_pdf']),maintype='application',subtype='pdf',filename='Note-de-frais-'+ref+'.pdf')
            try:send_notification(message)
            except Exception as error:
                with database() as db:
                    db.execute("UPDATE expense_notes SET mail_status='envoi à vérifier',last_error=? WHERE reference=?",(type(error).__name__,ref));audit(db,ref,'Incident lors de l’envoi : réception à vérifier')
            else:
                with database() as db:
                    db.execute("UPDATE expense_notes SET mail_status='accepté par le serveur mail',sent_at=?,last_error=NULL WHERE reference=?",(clock(),ref));audit(db,ref,'PDF accepté par le serveur mail')
        else:abort(404)
        return redirect(back,303)

    def issue(ref):
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            r=db.execute('SELECT * FROM registrations WHERE reference=?',(ref,)).fetchone();n=dict(db.execute('SELECT * FROM expense_notes WHERE reference=?',(ref,)).fetchone())
            if n['final_pdf']:return
            if not n['paid_at'] or not n['company_name'] or not n['company_address'] or not json.loads(r['payload']).get('vatNumber'):abort(409)
            n['issued_at']=clock();b=note_pdf(r,n,logo)
            db.execute('UPDATE expense_notes SET final_pdf=?,issued_at=?,updated_at=? WHERE reference=?',(b,n['issued_at'],clock(),ref));audit(db,ref,'Note de frais définitive générée et conservée')

    @app.get('/admin/inscriptions/<ref>/note.pdf')
    @admin_required
    def pdf(ref):
        pair=ensure(ref)
        if not pair:abort(404)
        r,n=pair
        if not json.loads(r['payload']).get('vatNumber'):abort(404)
        if not n['final_pdf'] and not n['draft_pdf']:save_draft(r,n);r,n=ensure(ref)
        b=n['final_pdf'] or n['draft_pdf']
        return Response(bytes(b),mimetype='application/pdf',headers={'Content-Disposition':'inline; filename="Note-de-frais-'+ref+'.pdf"'})

    return {'prepare_pending':prepare_pending,'ensure':ensure,'issue':issue}
