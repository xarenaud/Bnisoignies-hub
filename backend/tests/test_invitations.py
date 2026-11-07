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
                if kind=='ALUMNI':
                    self.assertEqual(msg['Subject'],'Et si on gardait le lien ? Découvre le HUB des anciens')
                    self.assertEqual(msg['Cc'],'hub@bim-soignies.be')
                    self.assertIn('Bonjour ALUMNI,',body)
                    for text in ['HUB – BIM','SUPER SUPPLÉANT','ont choisi d’activer cette liaison','Aucune obligation','+32 473 531 656','Le groupe HUB – BIM',r.get_json()['activationUrl']]:self.assertIn(text,body)
                    self.assertNotIn('BOM',body)
                else:
                    self.assertIn('Soignies',msg['Subject']);self.assertIsNone(msg['Cc']);self.assertNotIn('SUPER SUPPLÉANT',body)
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
    def test_substitution_confirmation_names_both_members_and_only_emails_recipient_once(self):
        day=datetime.utcnow().date()+timedelta(days=7)
        hub.db.session.add(hub.Meeting(date=day,type='REGULAR',status='PLANNED',location='Lieu de contrôle'))
        availability=hub.AlumniAvailability(member_id=self.ids['off'],date=day)
        hub.db.session.add(availability);hub.db.session.flush()
        item=hub.AlumniSubstitution(official_id=self.ids['active'],alumni_id=self.ids['off'],availability_id=availability.id,date=day)
        hub.db.session.add(item);hub.db.session.commit();rid=item.id
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false','APP_URL':'https://hub.test'}),patch.object(hub.smtplib,'SMTP') as smtp:
            r=self.client.patch(f'/api/alumni-space/substitutions/{rid}',headers=self.headers['off'],json={'status':'ACCEPTED'})
            self.assertEqual(r.status_code,200,r.get_json());self.assertTrue(r.get_json()['emailSent'])
            msg=smtp.return_value.send_message.call_args.args[0]
            self.assertEqual(msg['To'],'active@example.test');self.assertIsNone(msg['Cc']);self.assertIsNone(msg['Bcc'])
            self.assertIn('off Test a accepté de remplacer active Test le '+day.isoformat()+'.',msg.get_content())
            self.assertIn('https://hub.test/',msg.get_content())
            r=self.client.patch(f'/api/alumni-space/substitutions/{rid}',headers=self.headers['off'],json={'status':'ACCEPTED'})
            self.assertEqual(r.status_code,409);self.assertEqual(smtp.return_value.send_message.call_count,1)
    def test_smtp_failure_does_not_undo_confirmed_substitution(self):
        day=datetime.utcnow().date()+timedelta(days=7)
        hub.db.session.add(hub.Meeting(date=day,type='REGULAR',status='PLANNED',location='Lieu de contrôle'))
        availability=hub.AlumniAvailability(member_id=self.ids['off'],date=day)
        hub.db.session.add(availability);hub.db.session.flush()
        item=hub.AlumniSubstitution(official_id=self.ids['active'],alumni_id=self.ids['off'],availability_id=availability.id,date=day)
        hub.db.session.add(item);hub.db.session.commit();rid=item.id
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@example.test','SMTP_SSL':'false'}),patch.object(hub.smtplib,'SMTP',side_effect=OSError('Simulated unavailable mail server')),patch.object(hub.app.logger,'exception'):
            r=self.client.patch(f'/api/alumni-space/substitutions/{rid}',headers=self.headers['off'],json={'status':'ACCEPTED'})
            self.assertEqual(r.status_code,200);self.assertFalse(r.get_json()['emailSent'])
            self.assertEqual(hub.db.session.get(hub.AlumniSubstitution,rid).status,'ACCEPTED')
