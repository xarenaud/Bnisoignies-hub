import base64
import importlib
import os
import tempfile
import unittest
from unittest.mock import patch

storage = tempfile.TemporaryDirectory()
os.environ['BNI_EVENT_DATA_DIR'] = storage.name
os.environ['BNI_EVENT_ADMIN_PASSWORD'] = 'test-only-password'
import app


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        with app.database() as db:
            db.execute('DELETE FROM email_outbox')
            db.execute('DELETE FROM registrations')
            db.execute('DELETE FROM rate_limits')
        self.payload = {'firstName': 'Anne', 'lastName': 'Test', 'group': 'Un autre groupe', 'count': 3,
                        'guests': [{'firstName': 'Marc', 'lastName': 'A'}, {'firstName': 'Julie', 'lastName': 'B'}]}
        self.auth = {'Authorization': 'Basic ' + base64.b64encode(b'bni:test-only-password').decode()}

    def test_registration_total_retry_persistence(self):
        r = self.client.post('/register.php', json={**self.payload, 'total': 1})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json['total'], 45)
        self.assertEqual(self.client.post('/register.php', json=self.payload).json['reference'], r.json['reference'])
        importlib.reload(app)
        with app.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 1)

    def test_validation(self):
        for update in [{'count': 0}, {'count': True}, {'guests': []}, {'group': ' '}, {'firstName': '\n'}]:
            self.assertEqual(self.client.post('/register.php', json={**self.payload, **update}).status_code, 422)
        self.assertEqual(self.client.post('/register.php', data='bad', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post('/register.php', json=self.payload, headers={'Origin': 'https://evil.example'}).status_code, 403)

    def test_export_auth_and_csv(self):
        self.assertEqual(self.client.get('/admin/inscriptions.csv').status_code, 401)
        self.client.post('/register.php', json={**self.payload, 'lastName': '=1+1'})
        r = self.client.get('/admin/inscriptions.csv', headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertIn("'=1+1", r.text)
        self.assertIn('À vérifier par virement', r.text)

    def test_test_cleanup_protects_real_bookings(self):
        self.client.post('/register.php', json=self.payload)
        self.client.post('/register.php', json={**self.payload, 'isTest': True}, headers=self.auth)
        r = self.client.post('/api/admin/test-registrations/cleanup', headers=self.auth)
        self.assertEqual(r.json['removed'], 1)
        with app.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM registrations').fetchone()[0], 1)

    def test_email_content_retry_and_idempotency(self):
        r = self.client.post('/register.php', json=self.payload)
        self.client.post('/register.php', json=self.payload)
        with app.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM email_outbox').fetchone()[0], 1)
            row = db.execute('SELECT * FROM registrations').fetchone()
        with patch.dict(os.environ, {'SMTP_FROM': 'hub@bim-soignies.be'}):
            msg = app.notification_message(row)
        self.assertEqual(msg['To'], 'event@bim-soignies.be')
        for expected in ['45 EUR', 'Anne Test', 'Marc A', 'Julie B', 'Un autre groupe', 'à vérifier par virement']:
            self.assertIn(expected, msg.get_content())
        with patch.object(app, 'send_notification', side_effect=TimeoutError):
            self.assertTrue(app.deliver_pending())
        with app.database() as db:
            queued = db.execute('SELECT * FROM email_outbox').fetchone()
            self.assertEqual(queued['status'], 'pending')
            self.assertEqual(queued['last_error'], 'TimeoutError')
            db.execute('UPDATE email_outbox SET next_attempt=0')
        with patch.object(app, 'send_notification') as sender:
            self.assertTrue(app.deliver_pending())
            self.assertFalse(app.deliver_pending())
            sender.assert_called_once()
        with app.database() as db:
            self.assertEqual(db.execute('SELECT status FROM email_outbox').fetchone()[0], 'sent')

    def test_test_notifications_require_explicit_admin(self):
        self.client.post('/register.php', json={**self.payload, 'isTest': True}, headers=self.auth)
        with app.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM email_outbox').fetchone()[0], 0)
        self.client.post('/api/admin/test-registrations/cleanup', headers=self.auth)
        self.client.post('/register.php', json={**self.payload, 'isTest': True, 'notifyTest': True}, headers=self.auth)
        with app.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM email_outbox').fetchone()[0], 1)


    def test_static_assets_and_rate_limit(self):
        for path in ['/', '/event/', '/app.js', '/event/style.css', '/images/cocktail-professionnel.jpg', '/health']:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            r.close()
        for i in range(30):
            self.assertEqual(self.client.post('/register.php', json={**self.payload, 'lastName': str(i)}).status_code, 201)
        self.assertEqual(self.client.post('/register.php', json={**self.payload, 'lastName': 'extra'}).status_code, 429)


if __name__ == '__main__':
    unittest.main()
