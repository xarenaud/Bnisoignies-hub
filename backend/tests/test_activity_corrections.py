"""Administrative correction permissions, audit trail and recalculated totals."""
import json
import unittest
from datetime import date
from test_member_front import hub
import test_member_front as fixture

class ActivityCorrectionsTests(unittest.TestCase):
    def setUp(self):
        fixture.MemberFrontTests.setUp(self)
        self.record=hub.BusinessThanks(from_member_id=self.ids['active'],credited_member_id=self.ids['off'],amount=100,business_date=date.today(),notes='test')
        hub.db.session.add(self.record);hub.db.session.commit()
    def tearDown(self):fixture.MemberFrontTests.tearDown(self)
    def path(self,kind='business',record=None):return '/api/admin/network-records/'+kind+'/'+str(record or self.record.id)
    def row(self):return self.client.get('/api/admin/network-records',headers=self.headers['admin']).get_json()['items'][0]
    def test_only_current_directors_and_super_admin_can_correct(self):
        self.assertEqual(self.client.get('/api/admin/network-records').status_code,401)
        for who in ['active','off','former']:
            self.assertEqual(self.client.get('/api/admin/network-records',headers=self.headers[who]).status_code,403)
            self.assertEqual(self.client.patch(self.path(),headers=self.headers[who],json={}).status_code,403)
            self.assertEqual(self.client.delete(self.path(),headers=self.headers[who],json={}).status_code,403)
        role=hub.Role(name='Vice-président');hub.db.session.add(role);hub.db.session.flush()
        hub.db.session.add(hub.RoleAssignment(member_id=self.ids['active'],role_id=role.id,mandate_id=hub.Mandate.query.one().id,status='ACTIVE'));hub.db.session.commit()
        row=self.row()
        r=self.client.patch(self.path(),headers=self.headers['active'],json={'amount':'40.25','date':date.today().isoformat(),'reason':'Correction CA test','version':row['version']})
        self.assertEqual(r.status_code,200,r.get_json())
        self.assertEqual(self.record.amount,40.25)
        stats=self.client.get('/api/me/home',headers=self.headers['active']).get_json()['offActivity']
        self.assertEqual(stats['businessReceived'],40.25)
        log=hub.AuditLog.query.filter_by(action='ACTIVITY_CORRECTED').one();data=json.loads(log.details)
        self.assertEqual(data['reason'],'Correction CA test');self.assertEqual(data['before']['amount'],'100.00');self.assertEqual(data['after']['amount'],'40.25')
    def test_reason_values_and_stale_versions_protect_records(self):
        row=self.row();base={'amount':'50','date':date.today().isoformat(),'reason':'Correction test','version':row['version']}
        for amount in ['0','-1','nan','inf','0.001']:
            r=self.client.patch(self.path(),headers=self.headers['admin'],json={**base,'amount':amount});self.assertEqual(r.status_code,400,r.get_json())
        self.assertEqual(self.client.patch(self.path(),headers=self.headers['admin'],json={**base,'reason':''}).status_code,400)
        self.assertEqual(self.client.patch(self.path(),headers=self.headers['admin'],json={**base,'version':'old'}).status_code,409)
        self.assertEqual(self.client.patch(self.path(),headers=self.headers['admin'],json=base).status_code,200)
        self.assertEqual(self.client.delete(self.path(),headers=self.headers['admin'],json=base).status_code,409)
        self.assertEqual(hub.BusinessThanks.query.count(),1)
    def test_duplicate_removal_keeps_audit_and_recalculates_stats(self):
        rid=self.record.id;row=self.row()
        r=self.client.delete(self.path(),headers=self.headers['admin'],json={'version':row['version'],'reason':'Doublon de test'})
        self.assertEqual(r.status_code,200);self.assertIsNone(hub.db.session.get(hub.BusinessThanks,rid))
        stats=self.client.get('/api/me/home',headers=self.headers['active']).get_json()['offActivity'];self.assertEqual(stats['businessReceived'],0)
        history=self.client.get('/api/admin/network-records/history',headers=self.headers['admin']).get_json()
        self.assertEqual(history[0]['details']['reason'],'Doublon de test');self.assertEqual(history[0]['details']['before']['amount'],'100.00')
    def test_linked_referral_is_consistent_and_history_cannot_be_dropped_with_business(self):
        ref=hub.Referral(from_member_id=self.ids['off'],to_member_id=self.ids['active'],contact_name='Contact',status='WON')
        hub.db.session.add(ref);hub.db.session.flush();self.record.referral_id=ref.id;hub.db.session.commit()
        referral=self.client.get('/api/admin/network-records?kind=referrals',headers=self.headers['admin']).get_json()['items'][0]
        self.assertEqual(self.client.delete(self.path('referrals',ref.id),headers=self.headers['admin'],json={'version':referral['version'],'reason':'Erreur test'}).status_code,409)
        row=self.row();self.assertEqual(self.client.delete(self.path(),headers=self.headers['admin'],json={'version':row['version'],'reason':'MPB test à retirer'}).status_code,200)
        self.assertEqual(ref.status,'PENDING');self.assertIsNone(ref.closed_at)
        self.assertEqual(hub.ReferralStatusHistory.query.filter_by(referral_id=ref.id,status='PENDING').count(),1)
    def test_tat_and_recommendation_corrections(self):
        oto=hub.OneToOne(member_a_id=self.ids['active'],member_b_id=self.ids['off'],created_by_member_id=self.ids['active'],meeting_date=date.today())
        ref=hub.Referral(from_member_id=self.ids['active'],to_member_id=self.ids['off'],contact_name='Contact',estimated_value=20)
        hub.db.session.add_all([oto,ref]);hub.db.session.commit()
        for kind,record,fields in [('one-to-ones',oto,{'durationMinutes':45}),('referrals',ref,{'estimatedValue':'25.50'})]:
            row=self.client.get('/api/admin/network-records?kind='+kind,headers=self.headers['admin']).get_json()['items'][0]
            r=self.client.patch(self.path(kind,record.id),headers=self.headers['admin'],json={**fields,'date':date.today().isoformat(),'version':row['version'],'reason':'Date et chiffre corrigés'})
            self.assertEqual(r.status_code,200,r.get_json())
        self.assertEqual(oto.duration_minutes,45);self.assertEqual(float(ref.estimated_value),25.5)
