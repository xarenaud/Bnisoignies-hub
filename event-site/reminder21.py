"""Approved November 21 reminder: explicit scheduling and idempotent organizer test."""
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from flask import jsonify, request

CAMPAIGN = 'inter-bni-20261121-1700'
DUE = datetime(2026,11,21,17,0,tzinfo=ZoneInfo('Europe/Brussels')).timestamp()
SUBJECT = 'Inter-BNI du 26 novembre : inscriptions jusqu’au mardi 24 novembre'
TEMPLATE = 'mailing-inter-bni-rappel-20261121.html'

def install(app, database, admin_required, same_origin, exclude_registered, service, summary, send):
    @app.route('/api/admin/invitation-reminder-20261121', methods=['GET','POST'])
    @admin_required
    def reminder21_schedule():
        if request.method == 'POST':
            if not same_origin():
                return jsonify(error='Origine non autorisée.'),403
            html=(Path(app.static_folder)/TEMPLATE).read_text()
            with database() as db:
                db.execute('BEGIN IMMEDIATE')
                if not db.execute('SELECT 1 FROM invitation_campaigns WHERE id=?',(CAMPAIGN,)).fetchone():
                    if time.time() >= DUE:
                        return jsonify(error='La date programmée est passée.'),422
                    source='inter-bni-20261109-0750'
                    if db.execute('SELECT COUNT(*) FROM invitation_campaign_recipients WHERE campaign_id=?',(source,)).fetchone()[0]!=315:
                        return jsonify(error='Liste source inattendue.'),409
                    db.execute('INSERT INTO invitation_campaigns VALUES(?,?,?,?,?)',(CAMPAIGN,DUE,SUBJECT,html,datetime.now(ZoneInfo('Europe/Brussels')).isoformat()))
                    db.execute('INSERT INTO invitation_campaign_recipients(campaign_id,email) SELECT ?,email FROM invitation_campaign_recipients WHERE campaign_id=?',(CAMPAIGN,source))
                service['exclude'](db)
                exclude_registered(db,CAMPAIGN,due_only=False)
        result=summary(CAMPAIGN)
        return (jsonify(result),200) if result else (jsonify(error='Non programmée.'),404)

    @app.post('/api/admin/invitation-reminder-20261121/test')
    @admin_required
    def reminder21_test():
        if not same_origin():
            return jsonify(error='Origine non autorisée.'),403
        request_id='test-inter-bni-20261121-v1-xavier'
        with database() as db:
            db.execute('CREATE TABLE IF NOT EXISTS invitation_tests (request_id TEXT PRIMARY KEY,status TEXT NOT NULL,created_at TEXT NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT status FROM invitation_tests WHERE request_id=?',(request_id,)).fetchone()
            if previous:
                return jsonify(status=previous['status'],recipient='xavier@cx-com.be')
            db.execute('INSERT INTO invitation_tests VALUES(?,?,?)',(request_id,'sending',datetime.now(ZoneInfo('Europe/Brussels')).isoformat()))
        row=dict(id=CAMPAIGN,subject='[TEST] '+SUBJECT,email='xavier@cx-com.be',html=(Path(app.static_folder)/TEMPLATE).read_text())
        try:
            message=service['message'](row)
            message.replace_header('Message-ID','<'+request_id+'@event.bim-soignies.be>')
            send(message)
        except Exception as error:
            with database() as db:
                db.execute('UPDATE invitation_tests SET status=? WHERE request_id=?',('unknown',request_id))
            return jsonify(status='unknown',error=type(error).__name__),502
        with database() as db:
            db.execute('UPDATE invitation_tests SET status=? WHERE request_id=?',('accepted_by_smtp',request_id))
        return jsonify(status='accepted_by_smtp',recipient='xavier@cx-com.be',sender='hub@bim-soignies.be')
