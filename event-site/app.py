import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import smtplib
import ssl
import threading
from email.message import EmailMessage
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import Flask, Response, jsonify, redirect, request, send_from_directory, session

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['MAX_CONTENT_LENGTH'] = 65536
DATA = Path(os.environ.get('BNI_EVENT_DATA_DIR', '/data'))
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / 'registrations.sqlite3'
ADMIN_PASSWORD = os.environ.get('BNI_EVENT_ADMIN_PASSWORD', '')
RATE_SECRET = os.environ.get('BNI_EVENT_RATE_SECRET', ADMIN_PASSWORD)
app.config.update(
    SECRET_KEY=hashlib.sha256(('organizer-session:' + RATE_SECRET).encode()).hexdigest(),
    SESSION_COOKIE_NAME='bim_event_organizer',
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(days=90),
)

NOTIFICATIONS_ENABLED = os.environ.get('BNI_EVENT_NOTIFICATIONS_ENABLED', 'false').lower() == 'true'
NOTIFY_TO = os.environ.get('BNI_EVENT_NOTIFY_TO', 'event@bim-soignies.be')
mail_wake = threading.Event()
UNIT_PRICE = 10


def database():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    return db


with database() as db:
    db.executescript('''
    CREATE TABLE IF NOT EXISTS registrations (
      id INTEGER PRIMARY KEY, reference TEXT NOT NULL UNIQUE,
      fingerprint TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
      count INTEGER NOT NULL, total INTEGER NOT NULL,
      created_at TEXT NOT NULL, is_test INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS email_outbox (
      reference TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
      claimed_at REAL, sent_at TEXT, last_error TEXT
    );
    CREATE TABLE IF NOT EXISTS email_deliveries (
      reference TEXT NOT NULL, kind TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
      next_attempt REAL NOT NULL DEFAULT 0, claimed_at REAL, sent_at TEXT, last_error TEXT,
      PRIMARY KEY(reference,kind)
    );
    INSERT OR IGNORE INTO email_deliveries(reference,kind,status,attempts,next_attempt,claimed_at,sent_at,last_error)
      SELECT reference,'organizer',status,attempts,next_attempt,claimed_at,sent_at,last_error FROM email_outbox;
    INSERT OR IGNORE INTO email_deliveries(reference,kind)
      SELECT reference,'organizer' FROM registrations WHERE is_test=0;
    CREATE TABLE IF NOT EXISTS organizer_resends (
      request_id TEXT PRIMARY KEY, result TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS rate_limits (
      address_hash TEXT NOT NULL, window INTEGER NOT NULL, count INTEGER NOT NULL,
      PRIMARY KEY(address_hash, window)
    );
    ''')


def notification_message(row):
    payload = json.loads(row['payload'])
    participant = row['kind'] == 'participant'
    message = EmailMessage()
    marker = '[TEST] ' if row['is_test'] else ''
    title = 'Confirmation de votre inscription' if participant else f"Nouvelle inscription — {payload['firstName']} {payload['lastName']}"
    message['Subject'] = f"{marker}Inter BNI — {title} — {row['count']} place(s) — {row['reference']}"
    message['From'] = os.environ.get('SMTP_FROM', '').strip()
    message['To'] = payload['email'] if participant else NOTIFY_TO
    message['Reply-To'] = NOTIFY_TO
    attempt = row['attempts'] if 'attempts' in row.keys() else 0
    message['Message-ID'] = f"<{row['reference']}.{row['kind']}.{attempt}@event.bim-soignies.be>"
    guests = '\n'.join(f"  {i}. {g['firstName']} {g['lastName']}" for i, g in enumerate(payload['guests'], 1)) or '  Aucun'
    greeting = f"Bonjour {payload['firstName']},\nVotre inscription est enregistrée.\n" if participant else 'NOUVELLE INSCRIPTION\n'
    invoice = ('Facture / note de frais demandée — TVA : ' + payload.get('vatNumber', '')) if payload.get('invoiceRequested') else 'Facture / note de frais : non demandée'
    body = (
        ('ESSAI TECHNIQUE — NE PAS COMPTER\n\n' if row['is_test'] else '') + greeting + '\n'
        f"Inter BNI Soignies — jeudi 26 novembre 2026, de 7 h à 10 h 30\n"
        f"Garage Ford Steveny Soignies, chaussée de Mons 71, 7060 Soignies\n\n"
        f"Référence : {row['reference']}\nDate : {row['created_at']}\n"
        f"Personne qui paie : {payload['firstName']} {payload['lastName']}\n"
        f"Groupe : {payload['group']}\nEmail : {payload.get('email', 'Non renseigné')}\n"
        f"Téléphone : {payload.get('phone', 'Non renseigné')}\n{invoice}\n"
        f"Nombre total de places : {row['count']}\nMontant à payer : {row['total']} EUR\n\n"
        f"Accompagnants :\n{guests}\n\n"
        f"Paiement obligatoire par virement. Le montant reste dû même en cas d’absence.\n"
        f"Bénéficiaire : BNI SOIGNIES\nCompte : BE16 1431 1380 7474\n"
        f"Communication : {payload['lastName']} {payload['firstName']} {payload['group']}\n\n"
        f"Cette confirmation d’inscription ne confirme pas la réception du paiement.\n"
    )
    if payload.get('paymentAcceptedAt'):
        body += f"Engagement de paiement accepté le {payload['paymentAcceptedAt']} — {payload.get('paymentTerms', '')}\n"
    body += '\nSite : https://event.bim-soignies.be/\nContact : ' + NOTIFY_TO + '\n'
    message.set_content(body)
    return message


def send_notification(row):
    host = os.environ.get('SMTP_HOST', '').strip()
    sender = os.environ.get('SMTP_FROM', '').strip()
    if not host or not sender:
        raise RuntimeError('SMTP configuration missing')
    use_ssl = os.environ.get('SMTP_SSL', 'false').lower() in {'true', '1', 'yes'}
    use_tls = os.environ.get('SMTP_STARTTLS', 'true').lower() in {'true', '1', 'yes'}
    port = int(os.environ.get('SMTP_PORT', '465' if use_ssl else '587'))
    context = ssl.create_default_context()
    client = smtplib.SMTP_SSL(host, port, timeout=20, context=context) if use_ssl else smtplib.SMTP(host, port, timeout=20)
    with client:
        if not use_ssl and use_tls:
            client.starttls(context=context)
        username = os.environ.get('SMTP_USER', '').strip()
        if username:
            client.login(username, os.environ.get('SMTP_PASSWORD', ''))
        refused = client.send_message(row if isinstance(row, EmailMessage) else notification_message(row))
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


def deliver_pending():
    now = time.time()
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE email_deliveries SET status='pending' WHERE status='sending' AND claimed_at < ?", (now - 300,))
        row = db.execute("SELECT r.*, o.attempts, o.kind FROM email_deliveries o JOIN registrations r USING(reference) WHERE o.status='pending' AND o.next_attempt <= ? ORDER BY r.id LIMIT 1", (now,)).fetchone()
        if not row:
            return False
        db.execute("UPDATE email_deliveries SET status='sending', claimed_at=?, attempts=attempts+1 WHERE reference=? AND kind=?", (now, row['reference'], row['kind']))
    try:
        send_notification(row)
    except Exception as error:
        # Keep private SMTP replies and addresses out of logs and status responses.
        error_kind = type(error).__name__
        with database() as db:
            db.execute("UPDATE email_deliveries SET status='pending', next_attempt=?, last_error=? WHERE reference=? AND kind=?", (time.time() + min(3600, 30 * 2 ** min(row['attempts'], 7)), error_kind, row['reference'], row['kind']))
        app.logger.warning('Event notification pending %s (%s)', row['reference'], error_kind)
    else:
        with database() as db:
            db.execute("UPDATE email_deliveries SET status='sent', sent_at=?, last_error=NULL WHERE reference=? AND kind=?", (datetime.now(ZoneInfo('Europe/Brussels')).isoformat(), row['reference'], row['kind']))
        app.logger.info('Event notification accepted by SMTP: %s', row['reference'])
    return True


def notification_worker():
    while True:
        try:
            if deliver_pending():
                continue
            if globals().get("deliver_campaign") and deliver_campaign():
                mail_wake.wait(2)
                mail_wake.clear()
                continue
        except Exception:
            app.logger.error('Event notification worker temporarily unavailable')
        mail_wake.wait(15)
        mail_wake.clear()


if NOTIFICATIONS_ENABLED:
    threading.Thread(target=notification_worker, daemon=True, name='event-mail').start()


@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    if request.path in {'/static/mailing-inter-bni.html', '/static/mailing-inter-bni-rappel-20261112.html'}:
        # Presentation-only email preview: inline styles, no scripts or forms.
        response.headers['Content-Security-Policy'] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    if request.path.startswith(('/api', '/admin', '/register.php', '/event/register.php')):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.errorhandler(413)
def too_large(error):
    return jsonify(error='Requête trop volumineuse.'), 413


@app.get('/')
@app.get('/event/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.get('/event')
def event_redirect():
    return redirect('/event/', code=308)


@app.get('/style.css')
@app.get('/event/style.css')
def stylesheet():
    return send_from_directory(app.static_folder, 'style.css')


@app.get('/app.js')
@app.get('/event/app.js')
def javascript():
    return send_from_directory(app.static_folder, 'app.js')


@app.get('/images/<path:filename>')
@app.get('/event/images/<path:filename>')
def images(filename):
    return send_from_directory(Path(app.static_folder) / 'images', filename, max_age=3600)


@app.get('/health')
def health():
    with database() as db:
        db.execute('SELECT 1 FROM registrations LIMIT 1').fetchone()
    return jsonify(status='ok', storage='persistent')


def valid_name(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 100 and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def organizer_session_version():
    return hmac.new(RATE_SECRET.encode(), ('organizer:' + ADMIN_PASSWORD).encode(), hashlib.sha256).hexdigest()


def is_admin():
    auth = request.authorization
    basic = bool(ADMIN_PASSWORD and auth and auth.username == 'bni' and hmac.compare_digest(auth.password or '', ADMIN_PASSWORD))
    saved = session.get('organizer_version', '')
    cookie = bool(ADMIN_PASSWORD and isinstance(saved, str) and saved and hmac.compare_digest(saved, organizer_session_version()))
    return basic or cookie


def admin_required(fn):
    @wraps(fn)
    def decorated(*args, **kwargs):
        if not is_admin():
            if request.method == 'GET' and request.accept_mimetypes.best == 'text/html':
                return redirect('/admin/connexion', code=303)
            # Retain authenticated API access without triggering the browser's cached Basic dialog.
            return Response('Connectez-vous sur /admin/connexion.', 401)
        return fn(*args, **kwargs)
    return decorated


@app.route('/admin/connexion', methods=['GET', 'POST'])
def organizer_login():
    from html import escape
    error = ''
    status = 200
    if request.method == 'GET' and session.get('organizer_version') == organizer_session_version() and ADMIN_PASSWORD:
        return redirect('/admin/inscriptions', code=303)
    if not session.get('login_csrf'):
        session['login_csrf'] = secrets.token_urlsafe(32)
    if request.method == 'POST':
        supplied = request.form.get('csrf', '')
        expected = session.get('login_csrf', '')
        if not same_origin() or not supplied or not hmac.compare_digest(supplied, expected):
            error = 'La page de connexion a expiré. Réessayez avec ce formulaire.'
            status = 403
        else:
            address = request.headers.get('X-Real-IP', request.remote_addr or '')
            address_hash = hmac.new(RATE_SECRET.encode(), ('login:' + address).encode(), hashlib.sha256).hexdigest()
            window = int(time.time()) // 900
            with database() as db:
                db.execute('CREATE TABLE IF NOT EXISTS organizer_login_attempts (address_hash TEXT, window INTEGER, attempts INTEGER NOT NULL, PRIMARY KEY(address_hash,window))')
                db.execute('BEGIN IMMEDIATE') if not db.in_transaction else None
                db.execute('DELETE FROM organizer_login_attempts WHERE window < ?', (window,))
                previous = db.execute('SELECT attempts FROM organizer_login_attempts WHERE address_hash=? AND window=?', (address_hash,window)).fetchone()
                limited = bool(previous and previous['attempts'] >= 15)
                if not limited:
                    db.execute('INSERT INTO organizer_login_attempts VALUES(?,?,1) ON CONFLICT(address_hash,window) DO UPDATE SET attempts=attempts+1', (address_hash,window))
            if limited:
                error = 'Trop de tentatives. Réessayez dans 15 minutes.'
                status = 429
            elif (ADMIN_PASSWORD and request.form.get('username','').strip().lower() == 'bni' and
                  hmac.compare_digest(request.form.get('password','').strip(), ADMIN_PASSWORD)):
                with database() as db:
                    db.execute('DELETE FROM organizer_login_attempts WHERE address_hash=?', (address_hash,))
                session.clear()
                session['organizer_version'] = organizer_session_version()
                session.permanent = request.form.get('remember') == 'yes'
                return redirect('/admin/inscriptions', code=303)
            else:
                error = 'Identifiant ou mot de passe incorrect. Vérifiez la majuscule et le point d’interrogation final.'
                status = 401
    csrf = escape(session['login_csrf'], quote=True)
    body = '<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Connexion organisateur · BNI Soignies</title><link rel="stylesheet" href="/admin/connexion.css"></head><body><main><p class="brand">BNI SOIGNIES · INTER BNI</p><h1>Espace organisateur</h1><p>Connectez-vous pour consulter les inscrits et gérer les paiements et les notes de frais.</p>'
    if error:
        body += '<p class="error" role="alert">' + escape(error) + '</p>'
    body += '<form method="post" action="/admin/connexion"><input type="hidden" name="csrf" value="' + csrf + '"><label>Identifiant<input name="username" value="bni" autocomplete="username" autocapitalize="none" spellcheck="false" required></label><label>Mot de passe<input name="password" type="password" autocomplete="current-password" required></label><label class="remember"><input type="checkbox" name="remember" value="yes" checked> Rester connecté sur cet appareil pendant 90 jours</label><button type="submit">Se connecter</button></form></main></body></html>'
    return Response(body, status=status, mimetype='text/html')


@app.get('/admin/connexion.css')
def organizer_login_css():
    return Response('''*{box-sizing:border-box}body{margin:0;background:#101722;color:#eef1f6;font:16px/1.6 Arial,sans-serif;min-height:100vh;padding:40px 18px}main{max-width:480px;margin:30px auto;background:#1b2738;padding:34px;border-top:4px solid #cf2030}.brand{font-size:12px;letter-spacing:2px;font-weight:bold;color:#ffa4b3}h1{font-size:30px;line-height:1.25}label{display:block;margin-top:24px}input{display:block;width:100%;padding:14px;margin-top:7px;font:inherit;border:1px solid #8390a2;border-radius:4px;background:white;color:#142033}input:focus{outline:3px solid #ff9fb2}.remember{display:flex;align-items:flex-start;gap:10px;font-size:14px}.remember input{width:20px;height:20px;flex-shrink:0;margin:3px 0 0}button{width:100%;margin-top:26px;padding:15px;border:0;border-radius:4px;background:#cf2030;color:white;font:inherit;font-weight:bold;cursor:pointer}.error{padding:12px;background:#5b1528;color:white;border-left:3px solid #ff9fb2}@media(max-width:500px){body{padding:18px 12px}main{padding:24px 20px;margin:12px auto}}''', mimetype='text/css')


def same_origin():
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        return False
    origin = request.headers.get('Origin')
    return not origin or urlparse(origin).netloc.lower() == request.host.lower()


@app.post('/register.php')
@app.post('/event/register.php')
def register():
    if not same_origin():
        return jsonify(error='Origine non autorisée.'), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get('website'):
        return jsonify(error='Données invalides.'), 400
    count, guests = data.get('count'), data.get('guests')
    if (type(count) is not int or not 1 <= count <= 100 or
        not all(valid_name(data.get(k)) for k in ('firstName', 'lastName', 'group')) or
        not isinstance(guests, list) or len(guests) != count - 1 or
        not all(isinstance(g, dict) and valid_name(g.get('firstName')) and valid_name(g.get('lastName')) for g in guests)):
        return jsonify(error='Vérifiez le groupe et les noms de tous les participants.'), 422
    email = data.get('email')
    phone = data.get('phone')
    invoice = data.get('invoiceRequested', False)
    vat = data.get('vatNumber', '')
    if (not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email.strip()) or
        not isinstance(phone, str) or not re.fullmatch(r'[+0-9() .-]{6,35}', phone.strip()) or
        sum(c.isdigit() for c in phone) < 6 or type(invoice) is not bool or data.get('paymentAccepted') is not True):
        return jsonify(error='Renseignez un email, un téléphone valides et acceptez l’obligation de paiement.'), 422
    if invoice and (not isinstance(vat, str) or not re.fullmatch(r'[A-Za-z0-9 .-]{4,32}', vat.strip())):
        return jsonify(error='Renseignez le numéro de TVA pour la facture / note de frais.'), 422
    payload = {k: data[k].strip() for k in ('firstName', 'lastName', 'group')}
    payload.update(count=count, guests=[{k: g[k].strip() for k in ('firstName', 'lastName')} for g in guests])
    payload.update(email=email.strip().lower(), phone=phone.strip(), invoiceRequested=invoice, vatNumber=vat.strip().upper() if invoice else '', paymentAccepted=True, unitPrice=UNIT_PRICE, paymentTermsVersion='2026-11-06-v2', paymentTerms='Inscription avec obligation de paiement. Le montant total reste dû même en cas d’absence.')
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    is_test = bool(data.get('isTest') is True and is_admin())
    if is_test:
        fingerprint = 'test:' + fingerprint
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        # Idempotent retries return the same booking.
        existing = db.execute('SELECT reference,count,total FROM registrations WHERE fingerprint=?', (fingerprint,)).fetchone()
        if existing:
            return jsonify(dict(existing)), 200
        # Railway supplies X-Real-IP. No raw IP addresses are retained.
        address = request.headers.get('X-Real-IP', request.remote_addr or '')
        address_hash = hmac.new(RATE_SECRET.encode(), address.encode(), hashlib.sha256).hexdigest()
        window = int(time.time()) // 3600
        db.execute('DELETE FROM rate_limits WHERE window < ?', (window - 1,))
        previous = db.execute('SELECT count FROM rate_limits WHERE address_hash=? AND window=?', (address_hash, window)).fetchone()
        if previous and previous['count'] >= 30:
            return jsonify(error='Trop de tentatives. Veuillez réessayer plus tard.'), 429
        db.execute('INSERT INTO rate_limits VALUES (?,?,1) ON CONFLICT(address_hash,window) DO UPDATE SET count=count+1', (address_hash, window))
        reference = 'BNI-' + secrets.token_hex(5).upper()
        created_at = datetime.now(ZoneInfo('Europe/Brussels')).isoformat()
        payload['paymentAcceptedAt'] = created_at
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        db.execute('INSERT INTO registrations(reference,fingerprint,payload,count,total,created_at,is_test) VALUES(?,?,?,?,?,?,?)',
                   (reference, fingerprint, encoded, count, count * UNIT_PRICE, created_at, int(is_test)))
        if not is_test or (data.get('notifyTest') is True and is_admin()):
            db.executemany('INSERT INTO email_deliveries(reference,kind) VALUES(?,?)', [(reference, 'organizer'), (reference, 'participant')])
    mail_wake.set()
    return jsonify(reference=reference, count=count, total=count * UNIT_PRICE), 201


@app.get('/admin/inscriptions.csv')
@admin_required
def export():
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Référence', 'Date', 'Prénom payeur', 'Nom payeur', 'Groupe', 'Email', 'Téléphone', 'Facture / note de frais', 'TVA', 'Places', 'Total EUR', 'Accompagnants', 'Engagement accepté le', 'Conditions acceptées', 'Paiement'])
    # Avoid spreadsheet formula execution from user-controlled CSV fields.
    def cell(value):
        text = str(value)
        return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else text
    with database() as db:
        rows = db.execute('SELECT * FROM registrations WHERE is_test=0 ORDER BY id').fetchall()
    for row in rows:
        p = json.loads(row['payload'])
        writer.writerow([cell(x) for x in [row['reference'], row['created_at'], p['firstName'], p['lastName'], p['group'], p.get('email', ''), p.get('phone', ''), 'Oui' if p.get('invoiceRequested') else 'Non', p.get('vatNumber', ''), row['count'], row['total'], ', '.join(g['firstName']+' '+g['lastName'] for g in p['guests']), p.get('paymentAcceptedAt', ''), p.get('paymentTerms', ''), expense_payment_label(row['reference'])]])
    return Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename=BNI_Soignies_inscriptions.csv'})


@app.post('/api/admin/test-registrations/cleanup')
@admin_required
def clean_tests():
    if not same_origin():
        return jsonify(error='Origine non autorisée.'), 403
    with database() as db:
        db.execute('DELETE FROM email_outbox WHERE reference IN (SELECT reference FROM registrations WHERE is_test=1)')
        db.execute('DELETE FROM email_deliveries WHERE reference IN (SELECT reference FROM registrations WHERE is_test=1)')
        result = db.execute('DELETE FROM registrations WHERE is_test=1')
    return jsonify(removed=result.rowcount)


@app.get('/api/admin/notifications/status')
@admin_required
def notification_status():
    with database() as db:
        counts = {r['status']: r['n'] for r in db.execute('SELECT status, COUNT(*) n FROM email_deliveries GROUP BY status')}
        latest = [dict(r) for r in db.execute('SELECT reference,kind,status,attempts,sent_at,last_error FROM email_deliveries ORDER BY rowid DESC LIMIT 10')]
    return jsonify(enabled=NOTIFICATIONS_ENABLED, recipient=NOTIFY_TO, counts=counts, latest=latest)


@app.post('/api/admin/notifications/resend-organizer')
@admin_required
def resend_organizer():
    if not same_origin():
        return jsonify(error='Origine non autorisée.'), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error='Données invalides.'), 422
    refs = data.get('references')
    request_id = data.get('requestId')
    if (not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{12,80}', request_id) or
        not isinstance(refs, list) or not 1 <= len(refs) <= 50 or
        not all(isinstance(ref, str) and re.fullmatch(r'BNI-[A-F0-9]{10}', ref) for ref in refs)):
        return jsonify(error='Références ou identifiant de demande invalides.'), 422
    refs = list(dict.fromkeys(refs))
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT result FROM organizer_resends WHERE request_id=?', (request_id,)).fetchone()
        if existing:
            return jsonify(json.loads(existing['result']))
        eligible = []
        for ref in refs:
            row = db.execute("SELECT o.status FROM email_deliveries o JOIN registrations r USING(reference) WHERE o.reference=? AND o.kind='organizer' AND r.is_test=0", (ref,)).fetchone()
            if row and row['status'] == 'sent':
                db.execute("UPDATE email_deliveries SET status='pending',next_attempt=0,sent_at=NULL,last_error=NULL WHERE reference=? AND kind='organizer'", (ref,))
                eligible.append(ref)
        result = dict(queued=eligible, recipient=NOTIFY_TO)
        db.execute('INSERT INTO organizer_resends VALUES(?,?)', (request_id, json.dumps(result)))
    mail_wake.set()
    return jsonify(result)

# Organizer dashboard: live database on every request, refresh every 15 minutes.
def organizer_rows():
    with database() as db:
        return db.execute('SELECT r.*,n.paid_at AS payment_received_at,n.mail_status AS expense_mail_status FROM registrations r LEFT JOIN expense_notes n USING(reference) WHERE r.is_test=0 ORDER BY r.id DESC').fetchall()


@app.get('/admin/inscriptions')
@admin_required
def organizer_dashboard():
    from html import escape
    rows = organizer_rows()
    entries = []
    for row in rows:
        p = json.loads(row['payload'])
        guests = ', '.join(g['firstName'] + ' ' + g['lastName'] for g in p['guests']) or '—'
        values = [row['reference'], datetime.fromisoformat(row['created_at']).strftime('%d/%m/%Y %H:%M'), p['firstName'] + ' ' + p['lastName'], p['group'], p.get('email', ''), p.get('phone', ''), row['count'], str(row['total']) + ' €', guests, ('Oui — ' + p.get('vatNumber', '')) if p.get('invoiceRequested') else 'Non']
        values.append('Payé le ' + row['payment_received_at'] if row['payment_received_at'] else 'À vérifier')
        action_link = '<td><a href="/admin/inscriptions/' + row['reference'] + '/note">Paiement / note de frais</a></td>'
        entries.append('<tr>' + ''.join('<td>' + escape(str(v)) + '</td>' for v in values) + action_link + '</tr>')
    updated = datetime.now(ZoneInfo('Europe/Brussels')).strftime('%d/%m/%Y à %H:%M:%S')
    headers = ['Référence', 'Inscription', 'Personne qui paie', 'Groupe', 'Email', 'Téléphone', 'Places', 'Montant dû', 'Accompagnants', 'Facture / TVA', 'Paiement', 'Actions']
    html = '''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><meta http-equiv="refresh" content="900"><title>Inter BNI — Liste des inscrits</title><link rel="stylesheet" href="/admin/inscriptions.css"></head><body><main><p class="brand">BNI SOIGNIES · ESPACE ORGANISATEUR</p><h1>Liste des inscrits</h1><p>Inter BNI · 26 novembre 2026 · Ford Steveny Soignies</p>'''
    html += '<section class="stats"><div><strong>' + str(len(rows)) + '</strong> inscriptions</div><div><strong>' + str(sum(r['count'] for r in rows)) + '</strong> places</div><div><strong>' + str(sum(r['total'] for r in rows if not r['payment_received_at'])) + ' €</strong> restant à percevoir</div></section>'
    html += '<p>Dernière actualisation : ' + updated + ' (heure belge). Actualisation automatique toutes les 15 minutes tant que cette page reste ouverte.</p><nav><a class="button" href="/admin/inscriptions.xlsx">Télécharger Excel (.xlsx)</a><a href="/admin/inscriptions">Actualiser maintenant</a><a href="/admin/inscriptions.csv">Télécharger CSV</a></nav><p class="note">Les montants indiquent les sommes dues. La réception des virements doit être vérifiée séparément. Les anciennes inscriptions conservent leur tarif initial.</p><div class="table"><table><thead><tr>'
    html += ''.join('<th scope="col">' + h + '</th>' for h in headers) + '</tr></thead><tbody>' + (''.join(entries) or '<tr><td colspan="12">Aucune inscription pour le moment.</td></tr>') + '</tbody></table></div></main></body></html>'
    return Response(html, mimetype='text/html', headers={'X-Robots-Tag': 'noindex, nofollow'})


@app.get('/admin/inscriptions.css')
@admin_required
def organizer_css():
    return Response('''*{box-sizing:border-box}body{margin:0;background:#101722;color:#e9edf3;font:15px/1.6 Arial,sans-serif}main{max-width:1600px;margin:auto;padding:40px 24px}.brand{color:#ff879b;font-weight:bold;letter-spacing:2px}h1{font-size:38px;margin:16px 0 8px}.stats{display:flex;flex-wrap:wrap;gap:16px;margin:28px 0}.stats div{background:#202b3b;border-top:3px solid #cf2030;padding:18px 26px;min-width:180px}.stats strong{display:block;font-size:32px}nav{display:flex;align-items:center;gap:20px;flex-wrap:wrap;margin:24px 0}a{color:#ffadb9}.button{background:#cf2030;color:white;padding:12px 20px;text-decoration:none;font-weight:bold}.note{color:#bdc8d8;max-width:900px}.table{overflow-x:auto;background:#192332;border:1px solid #344154}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:13px 16px;border-bottom:1px solid #344154;vertical-align:top}th{background:#263348;white-space:nowrap}td{overflow-wrap:anywhere;min-width:110px}tr:nth-child(even){background:#1e2b3e}@media(max-width:600px){main{padding:24px 14px}h1{font-size:30px}.stats div{flex:1;min-width:140px}}''', mimetype='text/css')


@app.get('/admin/inscriptions.xlsx')
@admin_required
def organizer_excel():
    import zipfile
    from xml.sax.saxutils import escape
    rows = organizer_rows()
    data = [['Référence', 'Date', 'Prénom payeur', 'Nom payeur', 'Groupe', 'Email', 'Téléphone', 'Places', 'Total EUR', 'Accompagnants', 'Facture / note de frais', 'TVA', 'Paiement', 'Engagement accepté le']]
    for row in rows:
        p = json.loads(row['payload'])
        data.append([row['reference'], row['created_at'], p['firstName'], p['lastName'], p['group'], p.get('email', ''), p.get('phone', ''), row['count'], row['total'], ', '.join(g['firstName'] + ' ' + g['lastName'] for g in p['guests']), 'Oui' if p.get('invoiceRequested') else 'Non', p.get('vatNumber', ''), expense_payment_label(row['reference']), p.get('paymentAcceptedAt', '')])
    def xml_text(value):
        # Excel inline strings prevent formulas from user-provided text.
        return escape(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value)))
    sheet_rows = []
    for n, values in enumerate(data, 1):
        cells = []
        for col, value in enumerate(values):
            ref = chr(65 + col) + str(n)
            cells.append(f'<c r="{ref}"><v>{value}</v></c>' if isinstance(value, int) else f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{xml_text(value)}</t></is></c>')
        sheet_rows.append(f'<row r="{n}">' + ''.join(cells) + '</row>')
    sheet = '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols><col min="1" max="14" width="24" customWidth="1"/></cols><sheetData>' + ''.join(sheet_rows) + f'</sheetData><autoFilter ref="A1:N{len(data)}"/></worksheet>'
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Inscriptions" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', sheet)
    return Response(output.getvalue(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename=BNI_Soignies_inscriptions.xlsx'})


@app.post('/api/admin/invitation-test')
@admin_required
def invitation_test():
    if not same_origin():
        return jsonify(error='Origine non autorisée.'), 403
    # Restricted to the organizer's explicitly requested test address.
    recipient = 'xavier@cx-com.be'
    with database() as db:
        db.execute("CREATE TABLE IF NOT EXISTS invitation_tests (request_id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL)")
    data = request.get_json(silent=True) or {}
    request_id = data.get('requestId') if isinstance(data, dict) else None
    template = data.get('template', 'invitation') if isinstance(data, dict) else None
    if template not in {'invitation', 'rappel-20261112'}:
        return jsonify(error='Modèle invalide.'), 422
    reminder = template == 'rappel-20261112'
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{12,80}', request_id):
        return jsonify(error='Identifiant de demande invalide.'), 422
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT status FROM invitation_tests WHERE request_id=?', (request_id,)).fetchone()
        if existing:
            return jsonify(status=existing['status'], recipient=recipient)
        db.execute('INSERT INTO invitation_tests VALUES(?,?,?)', (request_id, 'sending', datetime.now(ZoneInfo('Europe/Brussels')).isoformat()))
    message = EmailMessage()
    message['Subject'] = ('[VALIDATION] RAPPEL : INTER BNI 26/11/2026 - Ford Steveny Soignies' if reminder else 'INTER BNI 26/11/2026 - Ford Steveny Soignies')
    message['From'] = 'hub@bim-soignies.be'
    message['To'] = recipient
    message['Reply-To'] = 'event@bim-soignies.be'
    message['Message-ID'] = '<' + request_id + '@event.bim-soignies.be>'
    from email.utils import formatdate
    message['Date'] = formatdate(localtime=False)
    message.set_content("INVITATION TEST — Inter BNI Soignies\nJeudi 26 novembre 2026, de 7 h à 10 h 30\nGarage Ford Steveny Soignies, chaussée de Mons 71, 7060 Soignies\n16 groupes, une volonté d’avancer ensemble !\nParticipation : 10 EUR par personne.\nInscription avec obligation de paiement, y compris en cas d’absence.\nInformations et inscription : https://event.bim-soignies.be/#inscription\nContact : event@bim-soignies.be\n")
    if reminder:
        message.set_content((Path(app.static_folder) / 'mailing-inter-bni-rappel-20261112.txt').read_text())
    html_name = 'mailing-inter-bni-rappel-20261112.html' if reminder else 'mailing-inter-bni.html'
    message.add_alternative((Path(app.static_folder) / html_name).read_text(), subtype='html')
    try:
        send_notification(message)
    except Exception as error:
        with database() as db:
            db.execute("UPDATE invitation_tests SET status='failed' WHERE request_id=?", (request_id,))
        return jsonify(status='failed', error=type(error).__name__, smtpCode=getattr(error, 'smtp_code', None)), 502
    with database() as db:
        db.execute("UPDATE invitation_tests SET status='accepted_by_smtp' WHERE request_id=?", (request_id,))
    return jsonify(status='accepted_by_smtp', recipient=recipient, sender='hub@bim-soignies.be', messageId=str(message['Message-ID']))

# Durable scheduled invitations. Recipients and approved HTML remain private in SQLite.
def campaign_tables():
    with database() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS invitation_campaigns (
          id TEXT PRIMARY KEY, due REAL NOT NULL, subject TEXT NOT NULL, html TEXT NOT NULL,
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS invitation_campaign_recipients (
          campaign_id TEXT NOT NULL, email TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          claimed_at REAL, sent_at TEXT, error TEXT, PRIMARY KEY(campaign_id,email));''')


campaign_tables()


def exclude_registered_campaign_recipients(db, campaign_id=None, due_only=True):
    # Match the current registration list immediately before claiming each message.
    # The organizer explicitly requested their own copy, even if already registered.
    scope = "AND campaign_id=?" if campaign_id else ""
    due = "AND campaign_id IN (SELECT id FROM invitation_campaigns WHERE due<=?)" if due_only else ""
    args = ([campaign_id] if campaign_id else []) + ([time.time()] if due_only else [])
    return db.execute(
        """UPDATE invitation_campaign_recipients
           SET status='excluded_registered',error='AlreadyRegistered'
           WHERE status='pending' AND lower(trim(email))<>'xavier@cx-com.be'
           AND EXISTS (
             SELECT 1 FROM registrations r WHERE r.is_test=0
             AND lower(trim(COALESCE(json_extract(r.payload,'$.email'),'')))=lower(trim(invitation_campaign_recipients.email))
           ) """ + scope + " " + due, args).rowcount


def campaign_summary(campaign_id):
    with database() as db:
        row = db.execute('SELECT id,due,subject FROM invitation_campaigns WHERE id=?', (campaign_id,)).fetchone()
        if not row:
            return None
        counts = {r['status']: r['n'] for r in db.execute('SELECT status,COUNT(*) n FROM invitation_campaign_recipients WHERE campaign_id=? GROUP BY status', (campaign_id,))}
        registered_pending = db.execute("SELECT COUNT(*) FROM invitation_campaign_recipients c WHERE c.campaign_id=? AND c.status='pending' AND lower(trim(c.email))<>'xavier@cx-com.be' AND EXISTS (SELECT 1 FROM registrations r WHERE r.is_test=0 AND lower(trim(COALESCE(json_extract(r.payload,'$.email'),'')))=lower(trim(c.email)))", (campaign_id,)).fetchone()[0]
    return dict(id=row['id'], scheduledFor=datetime.fromtimestamp(row['due'], ZoneInfo('Europe/Brussels')).isoformat(), subject=row['subject'], counts=counts, total=sum(counts.values()), registeredPendingExclusion=registered_pending, organizerCopy='xavier@cx-com.be')


@app.route('/api/admin/invitation-campaigns/<campaign_id>', methods=['GET', 'POST'])
@admin_required
def invitation_campaign(campaign_id):
    if not re.fullmatch(r'[a-z0-9-]{12,80}', campaign_id):
        return jsonify(error='Identifiant invalide.'), 422
    if request.method == 'GET':
        result = campaign_summary(campaign_id)
        return (jsonify(result), 200) if result else (jsonify(error='Envoi introuvable.'), 404)
    if not same_origin():
        return jsonify(error='Origine non autorisée.'), 403
    data = request.get_json(silent=True) or {}
    recipients = data.get('recipients') if isinstance(data, dict) else None
    if (not isinstance(recipients, list) or not 1 <= len(recipients) <= 1000 or
        not all(isinstance(e, str) and len(e) <= 254 and re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', e) for e in recipients)):
        return jsonify(error='Destinataires invalides.'), 422
    # One explicitly approved campaign, fixed date and subject, no immediate-send mode.
    if campaign_id != 'inter-bni-20261109-0750':
        return jsonify(error='Campagne non autorisée.'), 422
    due = datetime(2026, 11, 9, 7, 50, tzinfo=ZoneInfo('Europe/Brussels')).timestamp()
    recipients = list(dict.fromkeys(['xavier@cx-com.be'] + [e.lower() for e in recipients]))
    html = (Path(app.static_folder) / 'mailing-inter-bni.html').read_text()
    subject = 'INTER BNI 26/11/2026 - Ford Steveny Soignies'
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM invitation_campaigns WHERE id=?', (campaign_id,)).fetchone():
            if due <= time.time():
                return jsonify(error='La date programmée est passée.'), 422
            db.execute('INSERT INTO invitation_campaigns VALUES(?,?,?,?,?)', (campaign_id, due, subject, html, datetime.now(ZoneInfo('Europe/Brussels')).isoformat()))
            db.executemany('INSERT INTO invitation_campaign_recipients(campaign_id,email) VALUES(?,?)', [(campaign_id,e) for e in recipients])
    return jsonify(campaign_summary(campaign_id))



@app.post('/api/admin/invitation-reminder-20261112')
@admin_required
def schedule_invitation_reminder():
    if not same_origin():
        return jsonify(error='Origine non autorisée.'), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error='Données invalides.'), 422
    campaign_id = 'inter-bni-20261112-0815'
    source_id = 'inter-bni-20261109-0750'
    due = datetime(2026, 11, 12, 8, 15, tzinfo=ZoneInfo('Europe/Brussels')).timestamp()
    html = (Path(app.static_folder) / 'mailing-inter-bni-rappel-20261112.html').read_text()
    html_hash = hashlib.sha256(html.encode()).hexdigest()
    if data.get('approvedHtmlSha256') != html_hash:
        return jsonify(error='Le contenu ne correspond pas au mailing validé.'), 409
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM invitation_campaigns WHERE id=?', (campaign_id,)).fetchone():
            if due <= time.time():
                return jsonify(error='La date programmée est passée.'), 422
            source_count = db.execute('SELECT COUNT(*) FROM invitation_campaign_recipients WHERE campaign_id=?', (source_id,)).fetchone()[0]
            if source_count != 315:
                return jsonify(error='La liste source ne comporte pas les 315 adresses attendues.'), 409
            db.execute('INSERT INTO invitation_campaigns VALUES(?,?,?,?,?)', (
                campaign_id, due, 'RAPPEL : INTER BNI 26/11/2026 - Ford Steveny Soignies',
                html, datetime.now(ZoneInfo('Europe/Brussels')).isoformat()))
            db.execute("INSERT INTO invitation_campaign_recipients(campaign_id,email) SELECT ?,email FROM invitation_campaign_recipients WHERE campaign_id=?", (campaign_id,source_id))
            exclude_registered_campaign_recipients(db,campaign_id,due_only=False)
    result = campaign_summary(campaign_id)
    result.update(sourceCampaign=source_id, sender='hub@bim-soignies.be', htmlSha256=html_hash)
    return jsonify(result)


def deliver_campaign():
    now = time.time()
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        exclude_registered_campaign_recipients(db)
        # Do not silently resend after ambiguous delivery or a process restart.
        db.execute("UPDATE invitation_campaign_recipients SET status='unknown',error='DeliveryInterrupted' WHERE status='sending' AND claimed_at < ?", (now-300,))
        row = db.execute("SELECT c.id,c.subject,c.html,r.email FROM invitation_campaigns c JOIN invitation_campaign_recipients r ON r.campaign_id=c.id WHERE c.due<=? AND r.status='pending' ORDER BY c.due,r.rowid LIMIT 1", (now,)).fetchone()
        if not row:
            return False
        db.execute("UPDATE invitation_campaign_recipients SET status='sending',claimed_at=? WHERE campaign_id=? AND email=?", (now,row['id'],row['email']))
    message = EmailMessage()
    message['Subject'] = row['subject']
    message['From'] = 'hub@bim-soignies.be'
    message['To'] = row['email']
    message['Reply-To'] = 'event@bim-soignies.be'
    from email.utils import formatdate
    message['Date'] = formatdate(localtime=False)
    message['Message-ID'] = '<' + row['id'] + '.' + hashlib.sha256(row['email'].encode()).hexdigest()[:20] + '@event.bim-soignies.be>'
    message.set_content('Inter BNI — jeudi 26 novembre 2026, de 7 h à 10 h 30. Garage Ford Steveny Soignies, chaussée de Mons 71, 7060 Soignies. Participation : 10 EUR par personne. Inscription avec obligation de paiement, y compris en cas d’absence. Informations et inscription : https://event.bim-soignies.be/#inscription\nContact et retrait des invitations : event@bim-soignies.be')
    if row['id'] == 'inter-bni-20261112-0815':
        message.set_content((Path(app.static_folder) / 'mailing-inter-bni-rappel-20261112.txt').read_text())
    message.add_alternative(row['html'], subtype='html')
    try:
        send_notification(message)
    except Exception as error:
        status = 'failed' if isinstance(error, (smtplib.SMTPRecipientsRefused,smtplib.SMTPSenderRefused,smtplib.SMTPAuthenticationError)) else 'unknown'
        with database() as db:
            db.execute('UPDATE invitation_campaign_recipients SET status=?,error=? WHERE campaign_id=? AND email=?', (status,type(error).__name__,row['id'],row['email']))
    else:
        with database() as db:
            db.execute("UPDATE invitation_campaign_recipients SET status='accepted_by_smtp',sent_at=? WHERE campaign_id=? AND email=?", (datetime.now(ZoneInfo('Europe/Brussels')).isoformat(),row['id'],row['email']))
    return True


def expense_payment_label(ref):
    with database() as db:
        n = db.execute('SELECT paid_at FROM expense_notes WHERE reference=?',(ref,)).fetchone()
    return 'Payé le ' + n['paid_at'] if n and n['paid_at'] else 'À vérifier par virement'

from expense_notes import install as install_expense_notes
expense_service = install_expense_notes(app, database, admin_required, same_origin, send_notification, ADMIN_PASSWORD, NOTIFICATIONS_ENABLED)


