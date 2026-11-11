"""Isolation and consent regression tests. Uses the isolated fixture, no real e-mails."""
import hashlib
import unittest
from datetime import date, datetime, timedelta, time
from test_member_front import hub
import test_member_front as fixture

class AlumniSpacesTests(unittest.TestCase):
    def setUp(self):
        fixture.MemberFrontTests.setUp(self)
        for m in hub.Member.query.all():m.alumni_bridge_enabled=False
        self.add_member('off2','OFF','OFF')
        self.add_member('active2','ACTIVE','OFFICIAL_BNI')
        hub.db.session.commit()
    def tearDown(self):fixture.MemberFrontTests.tearDown(self)
    def add_member(self,key,status,network):
        m=hub.Member(first_name=key,last_name='Test',network_type=network)
        hub.db.session.add(m);hub.db.session.flush()
        a=hub.UserAccount(member_id=m.id,email=key+'@example.test',status='ACTIVE')
        hub.db.session.add(a);hub.db.session.flush()
        hub.db.session.add(hub.Membership(member_id=m.id,status=status,start_date=date.today()))
        hub.db.session.add(hub.AuthSession(account_id=a.id,token_hash=hashlib.sha256(key.encode()).hexdigest(),expires_at=datetime.utcnow()+timedelta(hours=1)))
        self.ids[key]=m.id;self.headers[key]={'Authorization':'Bearer '+key}
    def get(self,path,who='active'):return self.client.get(path,headers=self.headers[who])
    def post(self,path,data,who='active'):return self.client.post(path,headers=self.headers[who],json=data)
    def bridge(self,who='active',enabled=True):return self.client.put('/api/me/alumni-bridge',headers=self.headers[who],json={'enabled':enabled})
    def encode_all(self,actor,target,expected):
        for path,payload in [('referrals',{'toMemberId':self.ids[target],'contactName':'Contact'}),('business',{'creditedMemberId':self.ids[target],'amount':10}),('one-to-ones',{'partnerMemberId':self.ids[target]})]:
            r=self.post('/api/network/'+path,payload,actor)
            self.assertEqual(r.status_code,expected,(actor,target,path,r.get_json()))
    def test_default_official_space_keeps_communication_and_disables_encoding(self):
        self.assertFalse(self.get('/api/auth/me').get_json()['member']['networkAccessEnabled'])
        home=self.get('/api/me/home');self.assertEqual(home.status_code,200)
        self.assertIsNone(home.get_json()['memberStats']);self.assertIsNone(home.get_json()['groupStats'])
        self.encode_all('active','off',403)
        self.encode_all('admin','off',403)  # no consent implied by administrator status
        r=self.post('/api/me/requests',{'type':'COMMUNICATION','title':'Sujet','message':'Message'})
        self.assertEqual(r.status_code,201)
        self.assertEqual(self.get('/api/meetings').status_code,200)
        self.assertEqual(self.post('/api/network/visitors',{'name':'Invité'}).status_code,201)
        self.assertEqual(self.get('/api/me/past-stats').status_code,200)
    def test_legacy_global_flags_and_access_do_not_imply_consent(self):
        member=hub.db.session.get(hub.Member,self.ids['active']);member.network_access_enabled=True
        for key in ['NETWORK_MODULE','REFERRALS','BUSINESS','ONE_TO_ONE']:
            hub.db.session.add(hub.FeatureFlag(key=key,label=key,enabled=True))
        hub.db.session.commit()
        self.encode_all('active','off',403)
        self.assertFalse(self.get('/api/auth/me').get_json()['member']['networkAccessEnabled'])

    def test_pair_matrix_and_immediate_revocation(self):
        self.bridge('active');self.bridge('active2')
        self.encode_all('active','off',201)
        self.encode_all('off','active',201)
        self.encode_all('off','off2',201)
        self.encode_all('active','active2',201)
        self.encode_all('off','admin',403)
        self.encode_all('off','former',403)
        self.bridge('active',False)
        self.encode_all('active','off',403)
        self.encode_all('off','active',403)
        names=[x['id'] for x in self.get('/api/network/members','off').get_json()]
        self.assertNotIn(self.ids['active'],names)
        self.assertIn(self.ids['off2'],names)
        self.assertIn(self.ids['active2'],names)
        self.assertEqual(self.bridge('off').status_code,403)
        self.assertEqual(self.client.put('/api/me/alumni-bridge',json={'enabled':True}).status_code,401)

    def test_only_activated_accounts_can_receive_interactions(self):
        self.bridge('active2')
        for target in ['off2','active2']:
            member=hub.db.session.get(hub.Member,self.ids[target])
            account=member.user_account
            for status in ['INVITED','DISABLED','SUSPENDED']:
                account.status=status;hub.db.session.commit()
                with self.subTest(target=target,status=status):
                    ids=[m['id'] for m in self.get('/api/network/members','off').get_json()]
                    self.assertNotIn(member.id,ids)
                    self.encode_all('off',target,403)
            account.status='ACTIVE';hub.db.session.commit()
            self.assertIn(member.id,[m['id'] for m in self.get('/api/network/members','off').get_json()])
            self.encode_all('off',target,201)

        # Imported members with no account must also be absent and rejected.
        self.add_member('unregistered','OFF','OFF')
        member=hub.db.session.get(hub.Member,self.ids['unregistered'])
        hub.AuthSession.query.filter_by(account_id=member.user_account.id).delete()
        hub.db.session.delete(member.user_account);hub.db.session.commit()
        self.assertNotIn(member.id,[m['id'] for m in self.get('/api/network/members','off').get_json()])
        self.encode_all('off','unregistered',403)

        # The same rule applies when an opted-in official targets an alumnus.
        self.bridge('active')
        hub.db.session.get(hub.Member,self.ids['off2']).user_account.status='INVITED'
        hub.db.session.commit()
        self.assertNotIn(self.ids['off2'],[m['id'] for m in self.get('/api/network/members','active').get_json()])
        self.encode_all('active','off2',403)
    def test_alumni_cannot_read_official_space_even_with_old_board_role(self):
        mandate=hub.Mandate.query.first();role=hub.Role(name='Président');hub.db.session.add(role);hub.db.session.flush()
        hub.db.session.add(hub.RoleAssignment(member_id=self.ids['off'],role_id=role.id,mandate_id=mandate.id,status='ACTIVE'));hub.db.session.commit()
        me=self.get('/api/auth/me','off').get_json()['member']
        self.assertEqual(me['environment'],'ALUMNI');self.assertFalse(me['isAdmin']);self.assertEqual(me['roles'],[])
        for path in ['/api/meetings','/api/planning/welcome','/api/documents','/api/resources','/api/platforms','/api/vault','/api/me/duty-assignments','/api/duty-assignments','/api/swaps/open','/api/me/home','/api/mandates','/api/members','/api/member-requests','/api/network/hub-summary','/api/network/contributors']:
            self.assertEqual(self.get(path,'off').status_code,403,path)
        self.assertEqual(self.post('/api/me/requests',{'type':'COMMUNICATION','title':'x','message':'x'},'off').status_code,403)
        self.assertEqual(self.get('/api/me/requests','off').status_code,200)
    def test_departure_needs_request_and_retains_identity_business_and_history(self):
        self.bridge()
        self.encode_all('off','active',201)
        before=hub.Referral.query.count();business=hub.BusinessThanks.query.count();oto=hub.OneToOne.query.count()
        self.assertEqual(self.post(f'/api/members/{self.ids["active"]}/alumni-activate',{},'admin').status_code,400)
        self.assertEqual(self.post('/api/me/alumni-request',{}).status_code,200)
        self.assertEqual(self.get('/api/auth/me').get_json()['member']['environment'],'MEMBERS')
        self.assertEqual(self.post(f'/api/members/{self.ids["active"]}/alumni-activate',{},'admin').status_code,200)
        me=self.get('/api/auth/me').get_json()['member'];self.assertEqual(me['id'],self.ids['active']);self.assertEqual(me['environment'],'ALUMNI')
        self.assertEqual(self.get('/api/meetings').status_code,403)
        self.assertEqual(hub.Referral.query.count(),before);self.assertEqual(hub.BusinessThanks.query.count(),business);self.assertEqual(hub.OneToOne.query.count(),oto)
        self.assertEqual(len(self.get('/api/network/business').get_json()),1)
        memberships=hub.Membership.query.filter_by(member_id=self.ids['active']).order_by(hub.Membership.id).all()
        self.assertEqual([m.status for m in memberships],['FORMER','OFF'])
        self.assertEqual(self.get('/api/me/past-stats').status_code,200)
    def test_only_alumni_can_offer_and_all_official_members_can_request(self):
        day=(date.today()+timedelta(days=7)).isoformat()
        self.assertEqual(self.post('/api/alumni-space/availability',{'date':day}).status_code,403)
        offer=self.post('/api/alumni-space/availability',{'date':day,'note':'Disponible'},'off');self.assertEqual(offer.status_code,201)
        aid=offer.get_json()['id']
        self.assertEqual(self.get('/api/alumni-space/availability').status_code,200)
        self.assertEqual(self.get('/api/alumni-space/availability','former').status_code,403)
        self.assertEqual(self.post('/api/alumni-space/substitutions',{'availabilityId':aid},'former').status_code,403)
        self.assertEqual(len(self.get('/api/alumni-space/availability').get_json()),1)
        self.assertEqual(self.post('/api/alumni-space/substitutions',{'availabilityId':aid}).status_code,400)
        hub.db.session.add(hub.Meeting(date=date.fromisoformat(day),start_time=time(7),type='REGULAR',status='PLANNED',location='Lieu privé'));hub.db.session.commit()
        request=self.post('/api/alumni-space/substitutions',{'availabilityId':aid});self.assertEqual(request.status_code,201)
        rid=request.get_json()['id']
        self.assertEqual(self.get('/api/alumni-space/substitutions','off2').get_json(),[])
        self.assertEqual(self.get('/api/alumni-space/substitutions','off').get_json()[0]['location'],'Lieu privé')
        self.assertEqual(self.get('/api/meetings','off').status_code,403)
        self.assertEqual(self.client.patch(f'/api/alumni-space/substitutions/{rid}',headers=self.headers['off2'],json={'status':'ACCEPTED'}).status_code,404)
        self.assertEqual(self.client.patch(f'/api/alumni-space/substitutions/{rid}',headers=self.headers['off'],json={'status':'ACCEPTED'}).status_code,200)
        self.assertEqual(self.post('/api/alumni-space/substitutions',{'availabilityId':aid},'active2').status_code,409)
    def test_home_availability_without_bridge_respects_accounts_and_both_claim_paths(self):
        day=date.today()+timedelta(days=7)
        hub.db.session.add(hub.Meeting(date=day,start_time=time(7),type='REGULAR',status='PLANNED'))
        offer=hub.AlumniAvailability(member_id=self.ids['off'],date=day,active=True,note='Disponible pour remplacer')
        past=hub.AlumniAvailability(member_id=self.ids['off2'],date=date.today()-timedelta(days=1),active=True)
        hub.db.session.add_all([offer,past]);hub.db.session.commit()
        self.assertIsNone(self.get('/api/me/home').get_json()['offActivity'])
        rows=self.get('/api/me/home').get_json()['availableSubstitutes']
        self.assertEqual([r['memberId'] for r in rows],[self.ids['off']])
        self.assertEqual(rows[0]['date'],day.isoformat())
        offer.active=False;hub.db.session.commit()
        self.assertEqual(self.get('/api/me/home').get_json()['availableSubstitutes'],[])
        offer.active=True;member=hub.db.session.get(hub.Member,self.ids['off']);member.user_account.status='INVITED';hub.db.session.commit()
        self.assertEqual(self.get('/api/me/home').get_json()['availableSubstitutes'],[])
        member.user_account.status='ACTIVE';hub.db.session.commit()
        accepted=hub.AlumniReplacementNeed(official_id=self.ids['active'],alumni_id=self.ids['off'],date=day,status='ACCEPTED')
        hub.db.session.add(accepted);hub.db.session.commit()
        self.assertEqual(self.get('/api/me/home').get_json()['availableSubstitutes'],[])
        self.assertEqual(self.get('/api/alumni-space/availability').get_json(),[])
        accepted.status='CANCELLED';hub.db.session.commit()
        self.assertEqual(len(self.get('/api/me/home').get_json()['availableSubstitutes']),1)
        targeted=hub.AlumniSubstitution(official_id=self.ids['active'],alumni_id=self.ids['off'],availability_id=offer.id,date=day,status='ACCEPTED')
        hub.db.session.add(targeted);hub.db.session.commit()
        self.assertEqual(self.get('/api/me/home').get_json()['availableSubstitutes'],[])

    def test_legacy_admin_switch_requires_a_personal_departure_request(self):
        target=self.ids['active']
        self.assertEqual(self.post(f'/api/members/{target}/network',{'networkType':'OFF'},'admin').status_code,400)
        self.assertEqual(self.client.patch(f'/api/members/{target}',headers=self.headers['admin'],json={'status':'OFF'}).status_code,400)
        self.assertEqual(self.get('/api/auth/me').get_json()['member']['environment'],'MEMBERS')

    def test_official_welcome_rotation_and_swaps_continue_without_bridge(self):
        day=date.today()+timedelta(days=7)
        meeting=hub.Meeting(date=day,start_time=time(7),type='REGULAR',status='PLANNED')
        duty=hub.Duty(code='WELCOME',name='Accueil',active=True)
        hub.db.session.add_all([meeting,duty]);hub.db.session.flush()
        assignment=hub.DutyAssignment(member_id=self.ids['active'],meeting_id=meeting.id,duty_id=duty.id,status='PUBLISHED')
        hidden=hub.DutyAssignment(member_id=self.ids['off'],meeting_id=meeting.id,duty_id=duty.id,status='PUBLISHED')
        hub.db.session.add_all([assignment,hidden]);hub.db.session.commit()
        planning=self.get('/api/planning/welcome').get_json()
        self.assertEqual([a['memberId'] for a in planning[0]['assignments']],[self.ids['active']])
        self.assertEqual(self.post(f'/api/me/duty-assignments/{assignment.id}/unavailable',{}).status_code,200)
        swap=self.get('/api/swaps/open','active2').get_json()[0]
        self.assertEqual(self.post(f'/api/swaps/{swap["id"]}/volunteer',{},'active2').status_code,200)
        self.assertEqual(hub.db.session.get(hub.DutyAssignment,assignment.id).member_id,self.ids['active2'])

    def test_revoked_business_bridge_does_not_block_pending_replacement_acceptance(self):
        day=date.today()+timedelta(days=7);self.bridge()
        hub.db.session.add(hub.Meeting(date=day,start_time=time(7),type='REGULAR',status='PLANNED'));hub.db.session.commit()
        aid=self.post('/api/alumni-space/availability',{'date':day.isoformat()},'off').get_json()['id']
        rid=self.post('/api/alumni-space/substitutions',{'availabilityId':aid}).get_json()['id']
        self.bridge(enabled=False)
        self.assertEqual(self.client.patch(f'/api/alumni-space/substitutions/{rid}',headers=self.headers['off'],json={'status':'ACCEPTED'}).status_code,200)
        self.assertFalse(self.get('/api/auth/me').get_json()['member']['alumniBridgeEnabled'])
        self.encode_all('active','off',403)
        self.encode_all('off','active',403)

    def test_bridge_visibility_and_admin_diagnostics_for_every_membership_type(self):
        # Same personal choice for ordinary active, onboarding and system administrator.
        for who in ['active','active2','admin']:
            member=hub.db.session.get(hub.Member,self.ids[who]);member.network_access_enabled=False;hub.db.session.commit()
            data=self.get('/api/alumni-space/me',who).get_json();self.assertEqual(data['environment'],'MEMBERS')
            self.assertEqual(self.bridge(who,True).status_code,200)
            self.assertEqual(self.bridge(who,False).status_code,200)
        membership=hub.Membership.query.filter_by(member_id=self.ids['active2']).order_by(hub.Membership.id.desc()).first();membership.status='ONBOARDING';hub.db.session.commit()
        self.assertEqual(self.get('/api/alumni-space/me','active2').get_json()['environment'],'MEMBERS')
        self.assertEqual(self.bridge('active2',True).status_code,200)
        rows={r['id']:r for r in self.get('/api/members','admin').get_json()}
        for who in ['active','active2','admin']:self.assertTrue(rows[self.ids[who]]['canActivateAlumniBridge'])
        self.assertFalse(rows[self.ids['off']]['canActivateAlumniBridge']);self.assertEqual(rows[self.ids['off']]['environment'],'ALUMNI')
        self.assertFalse(rows[self.ids['former']]['canActivateAlumniBridge']);self.assertEqual(rows[self.ids['former']]['environment'],'INACTIVE')

if __name__=='__main__':unittest.main()
