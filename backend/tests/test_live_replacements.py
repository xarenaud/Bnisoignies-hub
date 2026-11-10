"""Production replacement route checks; local fixtures and captured SMTP only."""
import os
import unittest
from unittest.mock import patch
from datetime import date,timedelta,time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from test_member_front import hub
import test_alumni_spaces as fixture

class LiveReplacementTests(unittest.TestCase):
    add_member=fixture.AlumniSpacesTests.add_member
    bridge=fixture.AlumniSpacesTests.bridge
    post=fixture.AlumniSpacesTests.post
    get=fixture.AlumniSpacesTests.get
    def setUp(self):
        fixture.AlumniSpacesTests.setUp(self)
        self.day=date.today()+timedelta(days=7)
        self.meeting=hub.Meeting(date=self.day,start_time=time(7),type='REGULAR',status='PLANNED',location='Lieu privé de réunion')
        hub.db.session.add(self.meeting);hub.db.session.commit()
    def tearDown(self):fixture.AlumniSpacesTests.tearDown(self)
    def publish(self,who='active'):
        r=self.post('/api/alumni-space/replacement-needs',{'date':self.day.isoformat(),'note':'Besoin de remplacement'},who)
        self.assertEqual(r.status_code,201,r.get_json());return r.get_json()
    def accept(self,mid,who='off'):
        return self.post('/api/alumni-space/replacement-needs/'+str(mid),{},who)
    def test_access_dates_and_recipient_only_publication_mails(self):
        path='/api/alumni-space/replacement-needs'
        self.assertEqual(self.client.get(path).status_code,401)
        self.assertEqual(self.client.post(path,json={}).status_code,401)
        self.assertEqual(self.get(path).status_code,200)
        self.assertEqual(self.get(path,'former').status_code,403)
        self.assertEqual(self.post(path,{'date':self.day.isoformat()},'off').status_code,403)
        for day in ['bad',(date.today()-timedelta(days=1)).isoformat(),(self.day+timedelta(days=1)).isoformat()]:
            self.assertEqual(self.post(path,{'date':day}).status_code,400)
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false','APP_URL':'https://hub.test'}),patch.object(hub.smtplib,'SMTP') as smtp:
            need=self.publish();self.assertEqual(need['notifiedCount'],2);self.assertEqual(need['emailSentCount'],2)
            mails=[c.args[0] for c in smtp.return_value.send_message.call_args_list]
            self.assertEqual({m['To'] for m in mails},{'off@example.test','off2@example.test'})
            for m in mails:
                self.assertIsNone(m['Cc']);self.assertIsNone(m['Bcc']);self.assertIn('Suppléance recherchée',m['Subject']);self.assertIn('?substitutions=1',m.get_content())
        self.assertEqual(self.post(path,{'date':self.day.isoformat()}).status_code,409)
        self.assertEqual(self.get(path,'active2').get_json(),[])
        self.assertFalse(self.get('/api/auth/me').get_json()['member']['alumniBridgeEnabled'])
    def test_first_acceptance_names_and_private_meeting_details(self):
        need=self.publish();nid=need['id']
        self.assertIsNone(self.get('/api/alumni-space/replacement-needs','off').get_json()[0]['location'])
        self.assertEqual(self.accept(nid,'active').status_code,403)
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false'}),patch.object(hub.smtplib,'SMTP') as smtp:
            r=self.accept(nid);self.assertEqual(r.status_code,200,r.get_json());payload=r.get_json()
            self.assertEqual(payload['alumniId'],self.ids['off']);self.assertEqual(payload['officialId'],self.ids['active']);self.assertEqual(payload['location'],'Lieu privé de réunion')
            msg=next(c.args[0] for c in smtp.return_value.send_message.call_args_list if c.args[0]['To']=='active@example.test');self.assertEqual(msg['To'],'active@example.test');self.assertIn('off Test a accepté de remplacer active Test le '+self.day.isoformat(),msg.get_content())
            self.assertEqual(self.accept(nid,'off2').status_code,409);self.assertEqual(self.accept(nid).status_code,409);self.assertEqual(smtp.return_value.send_message.call_count,2)
        self.assertIsNone(self.get('/api/alumni-space/replacement-needs','off2').get_json()[0]['location'])
        notices=self.get('/api/me/notifications').get_json()['items'];notice=next(n for n in notices if n['title']=='Suppléance confirmée')
        self.assertIn('off Test a accepté de remplacer active Test',notice['message']);self.assertEqual(notice['link'],'substitutions')
    def test_business_opt_out_keeps_replacements_but_cancelled_meetings_are_blocked(self):
        nid=self.publish()['id'];self.bridge(enabled=False)
        self.assertEqual(self.get('/api/alumni-space/replacement-needs','off').get_json()[0]['id'],nid)
        self.meeting.status='CANCELLED';hub.db.session.commit();self.assertEqual(self.accept(nid).status_code,400)
        self.assertEqual(self.get('/api/alumni-space/replacement-needs','off').get_json(),[])
        self.meeting.status='PLANNED';hub.db.session.commit()
        self.assertEqual(self.client.delete(f'/api/alumni-space/replacement-needs/{nid}',headers=self.headers['off']).status_code,403)
        self.assertEqual(self.client.delete(f'/api/alumni-space/replacement-needs/{nid}',headers=self.headers['active']).status_code,200)
        self.assertEqual(self.accept(nid).status_code,409)
        self.assertEqual(self.publish()['id'],nid)
        self.assertEqual(self.accept(nid).status_code,200)
        self.assertFalse(self.get('/api/auth/me').get_json()['member']['alumniBridgeEnabled'])
    def test_open_and_targeted_requests_cannot_double_book(self):
        nid=self.publish()['id'];self.assertEqual(self.accept(nid).status_code,200)
        second=self.publish('active2')['id']
        self.assertEqual(self.accept(second).status_code,409)
        availability=hub.AlumniAvailability(member_id=self.ids['off2'],date=self.day);hub.db.session.add(availability);hub.db.session.commit()
        self.assertEqual(self.post('/api/alumni-space/substitutions',{'availabilityId':availability.id}).status_code,409)
        request=hub.AlumniSubstitution(official_id=self.ids['active2'],alumni_id=self.ids['off2'],availability_id=availability.id,date=self.day)
        hub.db.session.add(request);hub.db.session.commit()
        r=self.client.patch(f'/api/alumni-space/substitutions/{request.id}',headers=self.headers['off2'],json={'status':'ACCEPTED'});self.assertEqual(r.status_code,200,r.get_json())
        self.assertEqual(self.accept(second,'off2').status_code,409)
    def test_two_competing_claims_have_one_winner(self):
        nid=self.publish()['id'];hub.db.session.remove();barrier=Barrier(2)
        def claim(who):
            with hub.app.test_client() as client:
                barrier.wait(timeout=5)
                return client.post(f'/api/alumni-space/replacement-needs/{nid}',headers=self.headers[who],json={}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(claim,['off','off2']))
        self.assertEqual(sorted(statuses),[200,409])
        hub.db.session.expire_all();need=hub.db.session.get(hub.AlumniReplacementNeed,nid)
        self.assertEqual(need.status,'ACCEPTED');self.assertIn(need.alumni_id,[self.ids['off'],self.ids['off2']])
        self.assertEqual(hub.Notification.query.filter_by(member_id=self.ids['active'],title='Suppléance confirmée').count(),1)
