"""Persistent sessions retain explicit logout and password-reset revocation."""
import hashlib
import unittest
from datetime import datetime,timedelta
from test_member_front import hub
import test_member_front as fixture

class SessionsTests(unittest.TestCase):
    def setUp(self):fixture.MemberFrontTests.setUp(self)
    def tearDown(self):fixture.MemberFrontTests.tearDown(self)
    def test_login_issues_ninety_day_session(self):
        account=hub.UserAccount.query.filter_by(member_id=self.ids['active']).one();account.password_hash=hub.generate_password_hash('FixturePassword123');hub.db.session.commit()
        r=self.client.post('/api/auth/login',json={'email':account.email,'password':'FixturePassword123'})
        self.assertEqual(r.status_code,200);data=r.get_json();self.assertEqual(data['expiresInDays'],90)
        row=hub.AuthSession.query.filter_by(token_hash=hashlib.sha256(data['token'].encode()).hexdigest()).one()
        self.assertGreater(row.expires_at,datetime.utcnow()+timedelta(days=89))
    def test_existing_valid_session_is_upgraded_and_logout_still_revokes(self):
        token_hash=hashlib.sha256(b'active').hexdigest();row=hub.AuthSession.query.filter_by(token_hash=token_hash).one()
        row.expires_at=datetime.utcnow()+timedelta(hours=1);hub.db.session.commit()
        r=self.client.get('/api/auth/me',headers=self.headers['active']);self.assertEqual(r.status_code,200)
        self.assertEqual(r.get_json()['expiresInDays'],90);self.assertGreater(row.expires_at,datetime.utcnow()+timedelta(days=89))
        self.client.post('/api/auth/logout',headers=self.headers['active'])
        self.assertEqual(self.client.get('/api/auth/me',headers=self.headers['active']).status_code,401)
    def test_expired_or_disabled_account_cannot_renew(self):
        row=hub.AuthSession.query.filter_by(token_hash=hashlib.sha256(b'active').hexdigest()).one();row.expires_at=datetime.utcnow()-timedelta(seconds=1);hub.db.session.commit()
        self.assertEqual(self.client.get('/api/auth/me',headers=self.headers['active']).status_code,401)
        account=hub.UserAccount.query.filter_by(member_id=self.ids['off']).one();account.status='INVITED';hub.db.session.commit()
        self.assertEqual(self.client.get('/api/auth/me',headers=self.headers['off']).status_code,401)
