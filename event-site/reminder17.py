"""One approved Inter BNI reminder, with live registration count and durable opt-outs."""
import hashlib
import hmac
import json
import re
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from flask import Response, jsonify, request

CAMPAIGN = 'inter-bni-20261117-0800'
SOURCE = 'inter-bni-20261109-0750'
SUBJECT = 'RAPPEL : INTER BNI 26/11/2026 - Ford Steveny Soignies'
DUE = datetime(2026, 11, 17, 8, 0, tzinfo=ZoneInfo('Europe/Brussels')).timestamp()


def render_gauge(template, participants):
    count = max(0, int(participants))
    percent = min(count, 100)
    return (template.replace('__BNI_REGISTERED__', str(count))
            .replace('__BNI_PERCENT__', str(percent))
            .replace('__BNI_REMAINING__', str(100 - percent)))


class PlainMail(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'style', 'script'}:
            self.hidden += 1
        if tag in {'p', 'h1', 'h2', 'tr', 'br'} and not self.hidden:
            self.parts.append('\n')
        if tag == 'a' and not self.hidden:
            href = dict(attrs).get('href', '')
            if href.startswith(('https://', 'mailto:')):
                self.parts.append(' ' + href + ' ')

    def handle_endtag(self, tag):
        if tag in {'style', 'script'}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {'p', 'h1', 'h2', 'tr'} and not self.hidden:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def text(self):
        return re.sub(r'\n\s*\n+', '\n\n', ''.join(self.parts)).strip()


def install(app, database, admin_required, same_origin, rate_secret, exclude_registered):
    with database() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS invitation_opt_outs (
            email TEXT PRIMARY KEY, requested_at TEXT NOT NULL, reason TEXT NOT NULL)""")

    def exclude(db):
        return db.execute("""UPDATE invitation_campaign_recipients
            SET status='excluded_unsubscribed',error='OptOut'
            WHERE campaign_id=? AND status IN ('pending','excluded_registered')
            AND lower(trim(email)) IN (SELECT email FROM invitation_opt_outs)""", (CAMPAIGN,)).rowcount

    def token_for(email):
        return hmac.new(rate_secret.encode(), ('invitation-opt-out:' + email).encode(), hashlib.sha256).hexdigest()

    def message(row):
        with database() as db:
            participants = db.execute('SELECT COALESCE(SUM(count),0) FROM registrations WHERE is_test=0').fetchone()[0]
        email = row['email'].strip().lower()
        withdrawal_url = 'https://event.bim-soignies.be/invitations/retrait?' + urlencode(dict(email=email, token=token_for(email)))
        html = render_gauge(row['html'], participants)
        html = html.replace('mailto:event@bim-soignies.be?subject=Retrait%20des%20invitations', escape(withdrawal_url, quote=True))
        html = html.replace('prévenez-nous par email</a>', 'cliquez ici pour vous désinscrire</a>')
        parser = PlainMail()
        parser.feed(html)
        mail = EmailMessage()
        mail['Subject'] = row['subject']
        mail['From'] = 'hub@bim-soignies.be'
        mail['To'] = row['email']
        mail['Reply-To'] = 'event@bim-soignies.be'
        mail['Date'] = formatdate(localtime=False)
        mail['Message-ID'] = '<' + CAMPAIGN + '.' + hashlib.sha256(email.encode()).hexdigest()[:20] + '@event.bim-soignies.be>'
        mail['List-Unsubscribe'] = '<' + withdrawal_url + '>'
        mail.set_content(parser.text())
        mail.add_alternative(html, subtype='html')
        return mail

    @app.route('/invitations/retrait', methods=['GET', 'POST'])
    def invitation_withdrawal():
        email = request.args.get('email', '').strip().lower()
        token = request.args.get('token', '')
        if not email or not token or not hmac.compare_digest(token, token_for(email)):
            return Response('Lien de désinscription invalide.', 403)
        if request.method == 'POST':
            if not same_origin():
                return Response('Origine non autorisée.', 403)
            with database() as db:
                db.execute('INSERT OR IGNORE INTO invitation_opt_outs VALUES(?,?,?)',
                           (email, datetime.now(ZoneInfo('Europe/Brussels')).isoformat(), 'Demande via le lien du mailing'))
                exclude(db)
            return Response('<!doctype html><html lang="fr"><meta charset="utf-8"><title>Désinscription confirmée</title><p>Votre désinscription est enregistrée. Vous ne recevrez plus nos invitations.</p></html>', mimetype='text/html')
        return Response('<!doctype html><html lang="fr"><meta charset="utf-8"><title>Ne plus recevoir nos invitations</title><p>Confirmez votre désinscription des invitations BNI Soignies.</p><form method="post"><button type="submit">Me désinscrire</button></form></html>', mimetype='text/html',
                        headers={'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex,nofollow'})

    @app.route('/api/admin/invitation-opt-outs', methods=['GET', 'POST'])
    @admin_required
    def invitation_opt_out_admin():
        if request.method == 'POST':
            if not same_origin():
                return jsonify(error='Origine non autorisée.'), 403
            data = request.get_json(silent=True) or {}
            emails = data.get('emails') if isinstance(data, dict) else None
            if not isinstance(emails, list) or len(emails) > 1000 or not all(isinstance(e, str) and len(e) <= 254 and re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', e) for e in emails):
                return jsonify(error='Adresses invalides.'), 422
            with database() as db:
                db.executemany('INSERT OR IGNORE INTO invitation_opt_outs VALUES(?,?,?)',
                               [(e.strip().lower(), datetime.now(ZoneInfo('Europe/Brussels')).isoformat(), 'Demande de retrait vérifiée par organisateur') for e in emails])
                exclude(db)
        with database() as db:
            count = db.execute('SELECT COUNT(*) FROM invitation_opt_outs').fetchone()[0]
        return jsonify(count=count)

    template = (Path(app.static_folder) / 'mailing-inter-bni-rappel-20261117.html').read_text()
    for marker in ['__BNI_REGISTERED__', '__BNI_PERCENT__', '__BNI_REMAINING__']:
        if marker not in template:
            raise RuntimeError('Reminder gauge marker missing')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        exists = db.execute('SELECT 1 FROM invitation_campaigns WHERE id=?', (CAMPAIGN,)).fetchone()
        if not exists and time.time() < DUE:
            source_count = db.execute('SELECT COUNT(*) FROM invitation_campaign_recipients WHERE campaign_id=?', (SOURCE,)).fetchone()[0]
            if source_count == 315:
                db.execute('INSERT INTO invitation_campaigns VALUES(?,?,?,?,?)',
                           (CAMPAIGN, DUE, SUBJECT, template, datetime.now(ZoneInfo('Europe/Brussels')).isoformat()))
                db.execute('INSERT INTO invitation_campaign_recipients(campaign_id,email) SELECT ?,email FROM invitation_campaign_recipients WHERE campaign_id=?', (CAMPAIGN, SOURCE))
            else:
                app.logger.error('Reminder17 not scheduled: expected 315 source recipients, got %s', source_count)
        exclude(db)
        exclude_registered(db, CAMPAIGN, due_only=False)
    with database() as db:
        record = db.execute('SELECT id,due,subject FROM invitation_campaigns WHERE id=?', (CAMPAIGN,)).fetchone()
        counts = {r['status']: r['n'] for r in db.execute('SELECT status,COUNT(*) n FROM invitation_campaign_recipients WHERE campaign_id=? GROUP BY status', (CAMPAIGN,))}
        participants = db.execute('SELECT COALESCE(SUM(count),0) FROM registrations WHERE is_test=0').fetchone()[0]
    app.logger.warning('REMINDER17_SCHEDULE_VERIFIED %s', json.dumps(dict(
        id=CAMPAIGN, exists=bool(record), scheduledFor=datetime.fromtimestamp(record['due'], ZoneInfo('Europe/Brussels')).isoformat() if record else None,
        counts=counts, total=sum(counts.values()), participants=participants, subject=record['subject'] if record else None), ensure_ascii=False))
    return dict(exclude=exclude, message=message)
