"""Real account support sessions: separate identity, read-only, expiry and audit."""
import hashlib
import unittest
from datetime import datetime,timedelta
from test_member_front import hub
import test_member_front as fixture

class SupportSessionsTests(unittest.TestCase):
    def setUp(self):fixture.MemberFrontTests.setUp(self)
    def tearDown(self):fixture.MemberFrontTests.tearDown(self)
    def start(self,who='active',actor='admin'):
        return self.client.post('/api/system/support-sessions',headers=self.headers[actor],json={'memberId':self.ids[who]})
    def delegated(self,who='active'):
        r=self.start(who);self.assertEqual(r.status_code,201,r.get_json());return {'Authorization':'Bearer '+r.get_json()['token']},r.get_json()
    def test_admin_can_inspect_real_profile_without_changing_account_or_normal_session(self):
        target=hub.UserAccount.query.filter_by(member_id=self.ids['active']).one();before=(target.password_hash,target.status)
        headers,data=self.delegated();r=self.client.get('/api/auth/me',headers=headers)
        self.assertEqual(r.status_code,200);member=r.get_json()['member'];self.assertEqual(member['id'],self.ids['active']);self.assertTrue(member['supportSession']);self.assertFalse(member['isAdmin']);self.assertFalse(member['isSystemAdmin'])
        support=hub.AuthSession.query.filter_by(token_hash=hashlib.sha256(data['token'].encode()).hexdigest()).one();self.assertLessEqual(support.expires_at,datetime.utcnow()+timedelta(minutes=30))
        old=support.expires_at;self.client.get('/api/auth/me',headers=headers);self.assertEqual(support.expires_at,old)
        self.assertEqual(self.client.get('/api/me/profile',headers=headers).status_code,200)
        self.assertEqual(self.client.get('/api/auth/me',headers=self.headers['active']).status_code,200)
        self.assertEqual((target.password_hash,target.status),before)
        self.assertEqual(self.client.get('/api/auth/me',headers=self.headers['admin']).get_json()['member']['id'],self.ids['admin'])
        stop=self.client.post('/api/system/support-sessions/stop',headers=headers);self.assertEqual(stop.status_code,200)
        self.assertEqual(self.client.get('/api/auth/me',headers=headers).status_code,401)
        actions=[r.action for r in hub.AuditLog.query.all()];self.assertIn('SUPPORT_SESSION_STARTED',actions);self.assertIn('SUPPORT_SESSION_STOPPED',actions)
    def test_no_admin_actions_or_member_mutations_are_allowed(self):
        self.assertEqual(self.start(actor='active').status_code,403)
        self.assertEqual(self.start('admin').status_code,403)
        account=hub.UserAccount.query.filter_by(member_id=self.ids['former']).one();account.status='INVITED';hub.db.session.commit();self.assertEqual(self.start('former').status_code,400)
        headers,_=self.delegated()
        for method,path,payload in [('get','/api/members',None),('get','/api/system/features',None),('post','/api/system/mail-test',{}),('get','/api/network/leaderboard',None),('put','/api/me/alumni-bridge',{'enabled':False}),('patch','/api/me/profile',{'firstName':'Changed'}),('post','/api/network/referrals',{}),('post','/api/auth/forgot-password',{'email':'active@example.test'}),('post','/api/auth/logout',{}),('post','/api/system/support-sessions',{'memberId':self.ids['off']})]:
            kwargs={'headers':headers}
            if payload is not None:kwargs['json']=payload
            self.assertEqual(getattr(self.client,method)(path,**kwargs).status_code,403,path)
        self.assertEqual(hub.db.session.get(hub.Member,self.ids['active']).first_name,'active')
    def test_alumni_environment_remains_isolated(self):
        headers,_=self.delegated('off')
        self.assertEqual(self.client.get('/api/auth/me',headers=headers).get_json()['member']['environment'],'ALUMNI')
        self.assertEqual(self.client.get('/api/meetings',headers=headers).status_code,403)
        self.assertEqual(self.client.get('/api/network/members',headers=headers).status_code,200)
    def test_alumni_support_view_only_lists_activated_recipients(self):
        pending=hub.Member(first_name='Pending',last_name='Alumnus',network_type='OFF')
        hub.db.session.add(pending);hub.db.session.flush()
        hub.db.session.add(hub.Membership(member_id=pending.id,status='OFF'))
        account=hub.UserAccount(member_id=pending.id,email='pending@example.test',status='INVITED')
        hub.db.session.add(account);hub.db.session.commit()
        headers,_=self.delegated('off')
        ids=[m['id'] for m in self.client.get('/api/network/members',headers=headers).get_json()]
        self.assertNotIn(pending.id,ids)
        self.assertIn(self.ids['active'],ids)
        account.status='ACTIVE';hub.db.session.commit()
        ids=[m['id'] for m in self.client.get('/api/network/members',headers=headers).get_json()]
        self.assertIn(pending.id,ids)
    def test_expiry_or_revoked_parent_invalidates_support_only(self):
        headers,data=self.delegated();row=hub.AuthSession.query.filter_by(token_hash=hashlib.sha256(data['token'].encode()).hexdigest()).one();row.expires_at=datetime.utcnow()-timedelta(seconds=1);hub.db.session.commit()
        self.assertEqual(self.client.get('/api/auth/me',headers=headers).status_code,401)
        headers,data=self.delegated();self.client.post('/api/auth/logout',headers=self.headers['admin'])
        self.assertEqual(self.client.get('/api/auth/me',headers=headers).status_code,401)
        self.assertEqual(self.client.get('/api/auth/me',headers=self.headers['active']).status_code,200)
