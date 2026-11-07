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
            with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false','APP_URL':'https://cx-labs.be/Bnisoignies-hub'}),patch.object(hub.smtplib,'SMTP') as smtp:
                smtp.return_value.send_message.return_value={}
                r=self.client.post(f'/api/members/{mid}/invite',headers=self.headers['admin'])
                self.assertEqual(r.status_code,200,r.get_json());self.assertTrue(r.get_json()['emailSent'])
                msg=smtp.return_value.send_message.call_args_list[0].args[0];body=msg.get_content()
                self.assertEqual(msg['To'],kind.lower()+'@example.test')
                self.assertTrue(r.get_json()['activationUrl'].startswith('https://hub.bim-soignies.be/?activate='))
                self.assertNotIn('cx-labs',body)
                for text in ['Sur iPhone (Safari)','Sur Android (Google Chrome)','écran d’accueil','https://hub.bim-soignies.be/','48 heures','non le lien personnel']:
                    self.assertIn(text,body)
                if kind=='ALUMNI':
                    self.assertEqual(msg['Subject'],'Et si on gardait le lien ? Découvre le HUB des anciens')
                    self.assertEqual(msg['Cc'],'hub@bim-soignies.be')
                    self.assertTrue(r.get_json()['copyEmailSent'])
                    copied=smtp.return_value.send_message.call_args_list[1].args[0]
                    self.assertEqual(copied['To'],'hub@bim-soignies.be');self.assertIsNone(copied['Cc']);self.assertNotEqual(copied['Message-ID'],msg['Message-ID'])
                    self.assertEqual([call.kwargs['to_addrs'] for call in smtp.return_value.send_message.call_args_list],[[kind.lower()+'@example.test'],['hub@bim-soignies.be']])
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
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false','APP_URL':'https://cx-labs.be/Bnisoignies-hub'}),patch.object(hub.smtplib,'SMTP') as smtp:
            r=self.client.patch(f'/api/alumni-space/substitutions/{rid}',headers=self.headers['off'],json={'status':'ACCEPTED'})
            self.assertEqual(r.status_code,200,r.get_json());self.assertTrue(r.get_json()['emailSent'])
            msg=smtp.return_value.send_message.call_args.args[0]
            self.assertEqual(msg['To'],'active@example.test');self.assertIsNone(msg['Cc']);self.assertIsNone(msg['Bcc'])
            self.assertIn('off Test a accepté de remplacer active Test le '+day.isoformat()+'.',msg.get_content())
            self.assertIn('https://hub.bim-soignies.be/',msg.get_content())
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
    def test_reset_and_exchange_links_ignore_legacy_application_url(self):
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false','APP_URL':'https://cx-labs.be/Bnisoignies-hub'}),patch.object(hub.smtplib,'SMTP') as smtp:
            r=self.client.post('/api/auth/forgot-password',json={'email':'active@example.test'})
            self.assertEqual(r.status_code,200)
            reset=smtp.return_value.send_message.call_args.args[0].get_content()
            self.assertIn('https://hub.bim-soignies.be/?reset=',reset);self.assertNotIn('cx-labs',reset)
            for path,payload in [('referrals',{'toMemberId':self.ids['off'],'contactName':'Contact de vérification'}),('business',{'creditedMemberId':self.ids['off'],'amount':25}),('one-to-ones',{'partnerMemberId':self.ids['off']})]:
                r=self.client.post('/api/network/'+path,headers=self.headers['active'],json=payload)
                self.assertEqual(r.status_code,201,r.get_json())
                body=smtp.return_value.send_message.call_args.args[0].get_content()
                self.assertIn('https://hub.bim-soignies.be/?network=',body);self.assertNotIn('cx-labs',body)
            self.assertEqual(smtp.return_value.send_message.call_count,4)

    def test_archived_alumni_copy_is_sent_and_refusal_reported_separately(self):
        member=hub.db.session.get(hub.Member,self.ids['former']);member.email='former@example.test';hub.db.session.commit()
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false'}),patch.object(hub.smtplib,'SMTP') as smtp,patch.object(hub.app.logger,'warning'):
            smtp.return_value.send_message.side_effect=[{}, {'hub@bim-soignies.be':(550,b'Recipient refused')}]
            r=self.client.post(f'/api/members/{member.id}/invite',headers=self.headers['admin'])
            self.assertEqual(r.status_code,200,r.get_json());data=r.get_json()
            self.assertTrue(data['emailSent']);self.assertFalse(data['copyEmailSent']);self.assertEqual(data['copyEmail'],'hub@bim-soignies.be')
            self.assertEqual([c.kwargs['to_addrs'] for c in smtp.return_value.send_message.call_args_list],[['former@example.test'],['hub@bim-soignies.be']])
            self.assertEqual(hub.Membership.query.filter_by(member_id=member.id).first().status,'FORMER')
    def test_member_refusal_does_not_prevent_hub_copy_attempt(self):
        member=hub.db.session.get(hub.Member,self.ids['off']);member.email='off@example.test';hub.db.session.commit()
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false'}),patch.object(hub.smtplib,'SMTP') as smtp,patch.object(hub.app.logger,'exception'):
            smtp.return_value.send_message.side_effect=[hub.smtplib.SMTPRecipientsRefused({'off@example.test':(550,b'Refused')}),{}]
            r=self.client.post(f'/api/members/{member.id}/invite',headers=self.headers['admin'])
            self.assertEqual(r.status_code,200);self.assertFalse(r.get_json()['emailSent']);self.assertTrue(r.get_json()['copyEmailSent'])
            self.assertEqual(smtp.return_value.send_message.call_count,2)

    def test_retry_sends_only_hub_copy_and_preserves_invitation(self):
        account=hub.UserAccount.query.filter_by(member_id=self.ids['off']).one();account.status='INVITED';account.invitation_token='preserved-fixture';account.invitation_expires_at=datetime.utcnow()+timedelta(hours=12);hub.db.session.commit()
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false'}),patch.object(hub.smtplib,'SMTP') as smtp:
            smtp.return_value.send_message.return_value={}
            r=self.client.post(f'/api/members/{self.ids["off"]}/invite-copy',headers=self.headers['admin'])
            self.assertEqual(r.status_code,200,r.get_json());self.assertTrue(r.get_json()['copyEmailSent']);self.assertEqual(smtp.return_value.send_message.call_count,1)
            call=smtp.return_value.send_message.call_args;self.assertEqual(call.kwargs['to_addrs'],['hub@bim-soignies.be']);self.assertEqual(call.args[0]['To'],'hub@bim-soignies.be')
            self.assertIn('?activate=preserved-fixture',call.args[0].get_content());self.assertEqual(account.invitation_token,'preserved-fixture');self.assertEqual(account.status,'INVITED')
            self.assertEqual(self.client.post(f'/api/members/{self.ids["off"]}/invite-copy',headers=self.headers['active']).status_code,403)
    def test_copy_failure_has_precise_error_and_expired_invitation_is_not_recreated(self):
        account=hub.UserAccount.query.filter_by(member_id=self.ids['off']).one();account.status='INVITED';account.invitation_token='same-fixture';account.invitation_expires_at=datetime.utcnow()+timedelta(hours=12);hub.db.session.commit()
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false'}),patch.object(hub.smtplib,'SMTP') as smtp,patch.object(hub.app.logger,'warning'):
            smtp.return_value.send_message.return_value={'hub@bim-soignies.be':(550,b'Refused')}
            r=self.client.post(f'/api/members/{self.ids["off"]}/invite-copy',headers=self.headers['admin'])
            self.assertFalse(r.get_json()['copyEmailSent']);self.assertEqual(r.get_json()['copyEmailError']['smtpCode'],550);self.assertEqual(r.get_json()['copyEmailError']['code'],'RECIPIENT_REFUSED')
            account.invitation_expires_at=datetime.utcnow()-timedelta(hours=1);hub.db.session.commit()
            r=self.client.post(f'/api/members/{self.ids["off"]}/invite-copy',headers=self.headers['admin']);self.assertEqual(r.status_code,409)
            self.assertEqual(smtp.return_value.send_message.call_count,1);self.assertEqual(account.invitation_token,'same-fixture')
    def test_missing_mail_configuration_is_explicit_for_copy(self):
        account=hub.UserAccount.query.filter_by(member_id=self.ids['off']).one();account.status='INVITED';account.invitation_token='same-fixture';account.invitation_expires_at=datetime.utcnow()+timedelta(hours=12);hub.db.session.commit()
        with patch.dict(os.environ,{'SMTP_HOST':'','SMTP_FROM':''}),patch.object(hub.app.logger,'warning'):
            r=self.client.post(f'/api/members/{self.ids["off"]}/invite-copy',headers=self.headers['admin'])
            self.assertEqual(r.get_json()['copyEmailError']['code'],'MAIL_NOT_CONFIGURED');self.assertFalse(r.get_json()['copyEmailSent'])

    def test_mail_test_targets_only_hub_and_hides_authentication_secret(self):
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@example.test','SMTP_USER':'fixture-user','SMTP_SSL':'false'}),patch.object(hub.smtplib,'SMTP') as smtp,patch.object(hub.app.logger,'warning'):
            smtp.return_value.send_message.return_value={}
            r=self.client.post('/api/system/mail-test',headers=self.headers['admin']);self.assertEqual(r.status_code,200,r.get_json());self.assertTrue(r.get_json()['copyEmailSent'])
            self.assertEqual(smtp.return_value.send_message.call_args.kwargs['to_addrs'],['hub@bim-soignies.be'])
            self.assertEqual(self.client.post('/api/system/mail-test',headers=self.headers['active']).status_code,403)
            smtp.return_value.login.side_effect=hub.smtplib.SMTPAuthenticationError(535,b'secret-from-server')
            r=self.client.post('/api/system/mail-test',headers=self.headers['admin']);self.assertFalse(r.get_json()['copyEmailSent']);self.assertEqual(r.get_json()['copyEmailError']['code'],'SMTP_AUTH_FAILED');self.assertEqual(r.get_json()['copyEmailError']['smtpCode'],535);self.assertNotIn('secret-from-server',r.get_data(as_text=True))
