"""Invitation e-mail capture and alumni activation, without real delivery."""
import os
import unittest
from unittest.mock import patch
from datetime import datetime,timedelta
from urllib.parse import urlparse,parse_qs
from test_member_front import hub
import test_member_front as fixture

class InvitationTests(unittest.TestCase):
    def setUp(self):fixture.MemberFrontTests.setUp(self)
    def tearDown(self):fixture.MemberFrontTests.tearDown(self)
    def test_both_spaces_receive_installation_guide_and_open_correct_interface(self):
        for kind,environment in [('BNI','MEMBERS'),('ALUMNI','ALUMNI')]:
            r=self.client.post('/api/members',headers=self.headers['admin'],json={'memberType':kind,'firstName':kind,'lastName':'Invitation','email':kind.lower()+'@example.test'})
            self.assertEqual(r.status_code,201);mid=r.get_json()['id']
            with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false','APP_URL':'https://hub.test'}),patch.object(hub.smtplib,'SMTP') as smtp:
                r=self.client.post(f'/api/members/{mid}/invite',headers=self.headers['admin'])
                self.assertEqual(r.status_code,200,r.get_json());self.assertTrue(r.get_json()['emailSent'])
                msg=smtp.return_value.send_message.call_args.args[0];body=msg.get_content()
                self.assertEqual(msg['To'],kind.lower()+'@example.test')
                for text in ['Sur iPhone (Safari)','Sur Android (Google Chrome)','écran d’accueil','https://hub.test/','48 heures','non le lien personnel']:
                    self.assertIn(text,body)
                self.assertIn('Anciens' if kind=='ALUMNI' else 'Soignies',msg['Subject'])
            token=parse_qs(urlparse(r.get_json()['activationUrl']).query)['activate'][0]
            activated=self.client.post('/api/auth/activate',json={'token':token,'password':'FixturePassword123'})
            self.assertEqual(activated.status_code,200)
            login=self.client.post('/api/auth/login',json={'email':kind.lower()+'@example.test','password':'FixturePassword123'})
            self.assertEqual(login.status_code,200,login.get_json());self.assertEqual(login.get_json()['member']['environment'],environment)
            self.assertEqual(self.client.post('/api/auth/activate',json={'token':token,'password':'FixturePassword123'}).status_code,400)
    def test_expired_activation_link_reports_an_error(self):
        account=hub.UserAccount.query.filter_by(member_id=self.ids['off']).one()
        account.invitation_token='expired-fixture';account.invitation_expires_at=datetime.utcnow()-timedelta(hours=1);hub.db.session.commit()
        r=self.client.post('/api/auth/activate',json={'token':'expired-fixture','password':'FixturePassword123'})
        self.assertEqual(r.status_code,400);self.assertIn('expiré',r.get_json()['error'])
