import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import smtplib
import ssl
import threading
from email.message import EmailMessage
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import Flask, Response, jsonify, redirect, request, send_from_directory

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['MAX_CONTENT_LENGTH'] = 65536
DATA = Path(os.environ.get('BNI_EVENT_DATA_DIR', '/data'))
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / 'registrations.sqlite3'
ADMIN_PASSWORD = os.environ.get('BNI_EVENT_ADMIN_PASSWORD', '')
RATE_SECRET = os.environ.get('BNI_EVENT_RATE_SECRET', ADMIN_PASSWORD)
NOTIFICATIONS_ENABLED = os.environ.get('BNI_EVENT_NOTIFICATIONS_ENABLED', 'false').lower() == 'true'
NOTIFY_TO = os.environ.get('BNI_EVENT_NOTIFY_TO', 'event@bim-soignies.be')
mail_wake = threading.Event()


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
    INSERT OR IGNORE INTO email_outbox(reference) SELECT reference FROM registrations WHERE is_test=0;
    CREATE TABLE IF NOT EXISTS rate_limits (
      address_hash TEXT NOT NULL, window INTEGER NOT NULL, count INTEGER NOT NULL,
      PRIMARY KEY(address_hash, window)
    );
    ''')


def notification_message(row):
    payload = json.loads(row['payload'])
    message = EmailMessage()
    marker = '[TEST] ' if row['is_test'] else ''
    message['Subject'] = f"{marker}Inter BNI — {payload['firstName']} {payload['lastName']} — {row['count']} place(s) — {row['reference']}"
    message['From'] = os.environ.get('SMTP_FROM', '').strip()
    message['To'] = NOTIFY_TO
    message['Message-ID'] = f"<{row['reference']}@event.bim-soignies.be>"
    guests = '\n'.join(f"  {i}. {g['firstName']} {g['lastName']}" for i, g in enumerate(payload['guests'], 1)) or '  Aucun'
    message.set_content(
        f"{'INSCRIPTION DE TEST — NE PAS COMPTER' if row['is_test'] else 'NOUVELLE INSCRIPTION'}\n\n"
        f"Inter BNI Soignies — 26 novembre 2026, de 7 h à 10 h 30\n"
        f"Garage Ford Steveny Soignies\n\n"
        f"Référence : {row['reference']}\nDate : {row['created_at']}\n"
        f"Personne qui paie : {payload['firstName']} {payload['lastName']}\n"
        f"Groupe : {payload['group']}\nNombre total de places : {row['count']}\n"
        f"Montant à payer : {row['total']} EUR\n\nAccompagnants :\n{guests}\n\n"
        f"Paiement : à vérifier par virement. Cet email ne confirme pas la réception du paiement.\n"
        f"Bénéficiaire : BNI SOIGNIES\nCompte : BE16 1431 1380 7474\n"
        f"Communication : {payload['lastName']} {payload['firstName']} {payload['group']}\n\n"
        f"Site : https://event.bim-soignies.be/\n"
    )
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
        refused = client.send_message(notification_message(row))
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


def deliver_pending():
    now = time.time()
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE email_outbox SET status='pending' WHERE status='sending' AND claimed_at < ?", (now - 300,))
        row = db.execute("SELECT r.*, o.attempts FROM email_outbox o JOIN registrations r USING(reference) WHERE o.status='pending' AND o.next_attempt <= ? ORDER BY r.id LIMIT 1", (now,)).fetchone()
        if not row:
            return False
        db.execute("UPDATE email_outbox SET status='sending', claimed_at=?, attempts=attempts+1 WHERE reference=?", (now, row['reference']))
    try:
        send_notification(row)
    except Exception as error:
        # Keep private SMTP replies and addresses out of logs and status responses.
        error_kind = type(error).__name__
        with database() as db:
            db.execute("UPDATE email_outbox SET status='pending', next_attempt=?, last_error=? WHERE reference=?", (time.time() + min(3600, 30 * 2 ** min(row['attempts'], 7)), error_kind, row['reference']))
        app.logger.warning('Event notification pending %s (%s)', row['reference'], error_kind)
    else:
        with database() as db:
            db.execute("UPDATE email_outbox SET status='sent', sent_at=?, last_error=NULL WHERE reference=?", (datetime.now(ZoneInfo('Europe/Brussels')).isoformat(), row['reference']))
        app.logger.info('Event notification accepted by SMTP: %s', row['reference'])
    return True


def notification_worker():
    while True:
        try:
            if deliver_pending():
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


def is_admin():
    auth = request.authorization
    return bool(ADMIN_PASSWORD and auth and auth.username == 'bni' and hmac.compare_digest(auth.password or '', ADMIN_PASSWORD))


def admin_required(fn):
    @wraps(fn)
    def decorated(*args, **kwargs):
        if not is_admin():
            return Response('Accès réservé à l’organisateur.', 401, {'WWW-Authenticate': 'Basic realm="BNI Soignies"'})
        return fn(*args, **kwargs)
    return decorated


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
    payload = {k: data[k].strip() for k in ('firstName', 'lastName', 'group')}
    payload.update(count=count, guests=[{k: g[k].strip() for k in ('firstName', 'lastName')} for g in guests])
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
        db.execute('INSERT INTO registrations(reference,fingerprint,payload,count,total,created_at,is_test) VALUES(?,?,?,?,?,?,?)',
                   (reference, fingerprint, encoded, count, count * 15, created_at, int(is_test)))
        if not is_test or (data.get('notifyTest') is True and is_admin()):
            db.execute('INSERT INTO email_outbox(reference) VALUES(?)', (reference,))
    mail_wake.set()
    return jsonify(reference=reference, count=count, total=count * 15), 201


@app.get('/admin/inscriptions.csv')
@admin_required
def export():
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Référence', 'Date', 'Prénom payeur', 'Nom payeur', 'Groupe', 'Places', 'Total EUR', 'Accompagnants', 'Paiement'])
    # Avoid spreadsheet formula execution from user-controlled CSV fields.
    def cell(value):
        text = str(value)
        return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else text
    with database() as db:
        rows = db.execute('SELECT * FROM registrations WHERE is_test=0 ORDER BY id').fetchall()
    for row in rows:
        p = json.loads(row['payload'])
        writer.writerow([cell(x) for x in [row['reference'], row['created_at'], p['firstName'], p['lastName'], p['group'], row['count'], row['total'], ', '.join(g['firstName']+' '+g['lastName'] for g in p['guests']), 'À vérifier par virement']])
    return Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename=BNI_Soignies_inscriptions.csv'})


@app.post('/api/admin/test-registrations/cleanup')
@admin_required
def clean_tests():
    if not same_origin():
        return jsonify(error='Origine non autorisée.'), 403
    with database() as db:
        db.execute('DELETE FROM email_outbox WHERE reference IN (SELECT reference FROM registrations WHERE is_test=1)')
        result = db.execute('DELETE FROM registrations WHERE is_test=1')
    return jsonify(removed=result.rowcount)


@app.get('/api/admin/notifications/status')
@admin_required
def notification_status():
    with database() as db:
        counts = {r['status']: r['n'] for r in db.execute('SELECT status, COUNT(*) n FROM email_outbox GROUP BY status')}
        latest = [dict(r) for r in db.execute('SELECT reference,status,attempts,sent_at,last_error FROM email_outbox ORDER BY rowid DESC LIMIT 10')]
    return jsonify(enabled=NOTIFICATIONS_ENABLED, recipient=NOTIFY_TO, counts=counts, latest=latest)
