"""Only resolved committee identities receive confirmation, captured SMTP only."""
import os
import unittest
from unittest.mock import patch
from datetime import date,timedelta,time
from test_member_front import hub
import test_alumni_spaces as fixture

class WelcomeCommitteeMailTests(unittest.TestCase):
    add_member=fixture.AlumniSpacesTests.add_member
    bridge=fixture.AlumniSpacesTests.bridge
    post=fixture.AlumniSpacesTests.post
    get=fixture.AlumniSpacesTests.get
    def setUp(self):
        fixture.AlumniSpacesTests.setUp(self)
        self.day=date.today()+timedelta(days=7)
        hub.db.session.add(hub.Meeting(date=self.day,start_time=time(7),type='REGULAR',status='PLANNED',location='Salle du groupe'))
        for key,first,last in [('amelie','Amélie','LOEDT'),('simon','Simon','VANWYMEERSCH'),('other','Simon','Autre')]:
            self.add_member(key,'ACTIVE','OFFICIAL_BNI');m=hub.db.session.get(hub.Member,self.ids[key]);m.first_name=first;m.last_name=last
        hub.db.session.commit();self.bridge()
    def tearDown(self):fixture.AlumniSpacesTests.tearDown(self)
    def test_open_and_targeted_acceptances_each_notify_the_same_two_exact_people_once(self):
        for targeted in [False,True]:
            if targeted:
                offer=self.post('/api/alumni-space/availability',{'date':self.day.isoformat()},'off').get_json()
                rid=self.post('/api/alumni-space/substitutions',{'availabilityId':offer['id']}).get_json()['id']
                path='/api/alumni-space/substitutions/'+str(rid)
            else:
                rid=self.post('/api/alumni-space/replacement-needs',{'date':self.day.isoformat()}).get_json()['id']
                path='/api/alumni-space/replacement-needs/'+str(rid)
            with patch.dict(os.environ,{'SMTP_HOST':'smtp.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false'}),patch.object(hub.smtplib,'SMTP') as smtp:
                if targeted:r=self.client.patch(path,headers=self.headers['off'],json={'status':'ACCEPTED'})
                else:r=self.post(path,{},'off')
                self.assertEqual(r.status_code,200,r.get_json());self.assertEqual(r.get_json()['welcomeCommitteeEmails']['sentCount'],2)
                messages=[c.args[0] for c in smtp.return_value.send_message.call_args_list]
                self.assertEqual({m['To'] for m in messages},{'active@example.test','amelie@example.test','simon@example.test'})
                for m in messages:
                    self.assertIn('off Test a accepté de remplacer active Test',m.get_content())
                    if 'comité' in m['Subject']:
                        self.assertIn('07:00',m.get_content());self.assertIn('Salle du groupe',m.get_content());self.assertIn('?agenda=',m.get_content())
                if targeted:again=self.client.patch(path,headers=self.headers['off'],json={'status':'ACCEPTED'})
                else:again=self.post(path,{},'off')
                self.assertEqual(again.status_code,409);self.assertEqual(len(smtp.return_value.send_message.call_args_list),3)
            self.day+=timedelta(days=7)
            hub.db.session.add(hub.Meeting(date=self.day,start_time=time(7),type='REGULAR',status='PLANNED',location='Salle du groupe'));hub.db.session.commit()
    def test_ambiguous_identity_never_sends_to_a_first_name_guess(self):
        self.add_member('ambiguous','ACTIVE','OFFICIAL_BNI');duplicate=hub.db.session.get(hub.Member,self.ids['ambiguous']);duplicate.first_name='Simon';duplicate.last_name='Vanwymeersch';hub.db.session.commit()
        rid=self.post('/api/alumni-space/replacement-needs',{'date':self.day.isoformat()}).get_json()['id']
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false'}),patch.object(hub.smtplib,'SMTP') as smtp:
            r=self.post('/api/alumni-space/replacement-needs/'+str(rid),{},'off');self.assertEqual(r.status_code,200)
            self.assertEqual({c.args[0]['To'] for c in smtp.return_value.send_message.call_args_list},{'active@example.test','amelie@example.test'})
    def test_official_accepts_published_offer_once_and_notifies_all_parties(self):
        offer=self.post('/api/alumni-space/availability',{'date':self.day.isoformat()},'off').get_json()
        path='/api/alumni-space/availability/'+str(offer['id'])+'/accept'
        self.assertEqual(self.post(path,{},'off').status_code,403)
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false'}),patch.object(hub.smtplib,'SMTP') as smtp:
            r=self.post(path,{});self.assertEqual(r.status_code,201,r.get_json());self.assertEqual(r.get_json()['status'],'ACCEPTED')
            self.assertEqual({c.args[0]['To'] for c in smtp.return_value.send_message.call_args_list},{'active@example.test','off@example.test','amelie@example.test','simon@example.test'})
            self.assertEqual(self.post(path,{}).status_code,409)
            self.bridge('active2');self.assertEqual(self.post(path,{},'active2').status_code,409)
            self.assertEqual(smtp.return_value.send_message.call_count,4)
        self.assertEqual(self.get('/api/alumni-space/availability').get_json(),[])
