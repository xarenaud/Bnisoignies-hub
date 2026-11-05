"""Regression checks on an isolated SQLite database; no production data or email."""
import hashlib
import importlib.util
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, time

_temp=tempfile.TemporaryDirectory()
os.environ['DATABASE_URL']='sqlite:///'+_temp.name+'/hub.db'
os.environ.pop('SYSTEM_ADMIN_EMAIL',None)
os.environ.pop('SMTP_HOST',None)
spec=importlib.util.spec_from_file_location('hub_app',os.path.join(os.path.dirname(__file__),'..','app.py'))
hub=importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub)

class MemberFrontTests(unittest.TestCase):
    def setUp(self):
        self.ctx=hub.app.app_context();self.ctx.push()
        hub.db.drop_all();hub.db.create_all()
        self.client=hub.app.test_client();self.ids={};self.headers={}
        for key,status in [('active','ACTIVE'),('off','OFF'),('former','FORMER'),('admin','ACTIVE')]:
            m=hub.Member(first_name=key,last_name='Test',network_type='OFF' if key=='off' else 'OFFICIAL_BNI',network_access_enabled=False)
            hub.db.session.add(m);hub.db.session.flush()
            a=hub.UserAccount(member_id=m.id,email=key+'@example.test',status='ACTIVE',is_system_admin=key=='admin')
            hub.db.session.add(a);hub.db.session.flush()
            hub.db.session.add(hub.Membership(member_id=m.id,status=status,start_date=date.today()))
            hub.db.session.add(hub.AuthSession(account_id=a.id,token_hash=hashlib.sha256(key.encode()).hexdigest(),expires_at=datetime.utcnow()+timedelta(hours=1)))
            self.ids[key]=m.id;self.headers[key]={'Authorization':'Bearer '+key}
        hub.db.session.commit()

    def tearDown(self):
        hub.db.session.remove();self.ctx.pop()

    def test_every_current_member_can_encode_without_flags(self):
        for actor,partner in [('active','off'),('off','active'),('admin','off')]:
            headers=self.headers[actor]
            config=self.client.get('/api/network/config',headers=headers).get_json()
            self.assertTrue(config['features']['VISITORS'])
            members=self.client.get('/api/network/members',headers=headers).get_json()
            self.assertIn(self.ids[partner],[m['id'] for m in members])
            self.assertNotIn(self.ids['former'],[m['id'] for m in members])
            for path,payload in [
                ('referrals',{'toMemberId':self.ids[partner],'contactName':'Contact test'}),
                ('business',{'creditedMemberId':self.ids[partner],'amount':'150.50'}),
                ('one-to-ones',{'partnerMemberId':self.ids[partner]}),
                ('visitors',{'name':'Invité test'})]:
                r=self.client.post('/api/network/'+path,headers=headers,json=payload)
                self.assertEqual(r.status_code,201,(actor,path,r.get_json()))
                self.assertEqual(self.client.get('/api/network/'+path,headers=headers).status_code,200)
        stats=self.client.get('/api/network/stats',headers=self.headers['active']).get_json()
        self.assertEqual(stats['businessReceived'],150.5)
        self.assertEqual(stats['businessGenerated'],150.5)
        self.assertEqual(self.client.get('/api/network/stats',headers=self.headers['former']).status_code,403)
        self.assertEqual(self.client.get('/api/me/home').status_code,401)

    def test_home_published_duties_guests_and_private_resources(self):
        future=date.today()+timedelta(days=7)
        meeting=hub.Meeting(date=future,start_time=time(7),type='REGULAR',status='PLANNED',location='Lieu test')
        hub.db.session.add(meeting);hub.db.session.flush()
        duty=hub.Duty(code='TEST',name='Accueil',active=True)
        hub.db.session.add(duty);hub.db.session.flush()
        for status in ['PUBLISHED','DRAFT']:
            hub.db.session.add(hub.DutyAssignment(meeting_id=meeting.id,duty_id=duty.id,member_id=self.ids['active'],status=status))
        hub.db.session.add(hub.NetworkVisitor(invited_by_member_id=self.ids['off'],name='Invité OFF',visit_date=future,status='INVITED'))
        secret=hub.MemberRequest(member_id=self.ids['off'],type='COMMUNICATION',message='Confidentiel',attachment_data=b'test',attachment_name='test.txt')
        hub.db.session.add(secret);hub.db.session.commit()
        data=self.client.get('/api/me/home',headers=self.headers['active']).get_json()
        self.assertEqual(data['nextMeeting']['location'],'Lieu test')
        self.assertEqual(len(data['nextMeeting']['assignments']),1)
        self.assertEqual(data['nextMeeting']['guests'][0]['name'],'Invité OFF')
        self.assertEqual(self.client.get('/api/me/requests',headers=self.headers['active']).get_json(),[])
        self.assertEqual(self.client.get(f'/api/member-requests/{secret.id}/attachment',headers=self.headers['active']).status_code,403)

    def test_profile_and_transition_preserve_history(self):
        member_id=self.ids['off']
        hub.db.session.add(hub.MemberNetworkHistory(member_id=member_id,network_type='OFF',start_date=date.today()))
        hub.db.session.add(hub.OffMembership(member_id=member_id,plan_code='ANNUAL',status='ACTIVE',starts_at=date.today(),ends_at=date.today()+timedelta(days=365)))
        hub.db.session.commit()
        effective=(date.today()-timedelta(days=1)).isoformat()
        r=self.client.post(f'/api/members/{member_id}/network',headers=self.headers['admin'],json={'networkType':'OFF','effectiveDate':effective})
        self.assertEqual(r.status_code,200,r.get_json())
        history=self.client.get(f'/api/members/{member_id}/network-history',headers=self.headers['admin']).get_json()
        self.assertEqual(history[0]['startDate'],effective)
        profile=self.client.get('/api/me/profile',headers=self.headers['off']).get_json()
        self.assertIn('subscription',profile)
        self.assertEqual(profile['subscription']['startsAt'],date.today().isoformat())

if __name__=='__main__':unittest.main()
