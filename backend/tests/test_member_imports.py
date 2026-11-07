"""Member entry classification and atomic import checks, isolated database."""
import io
import unittest
from test_member_front import hub
import test_member_front as fixture
from openpyxl import Workbook

class MemberImportsTests(unittest.TestCase):
    def setUp(self):fixture.MemberFrontTests.setUp(self)
    def tearDown(self):fixture.MemberFrontTests.tearDown(self)
    def post(self,path,data,who='admin'):
        return self.client.post('/api/'+path,headers=self.headers[who],json=data)
    def test_individual_classification_drives_account_interface_without_inviting(self):
        before=hub.UserAccount.query.count()
        for kind,status,network,environment in [('BNI','ACTIVE','OFFICIAL_BNI','MEMBERS'),('ALUMNI','OFF','OFF','ALUMNI')]:
            r=self.post('members',{'firstName':kind,'lastName':'New','memberType':kind})
            self.assertEqual(r.status_code,201,r.get_json());data=r.get_json()
            self.assertEqual(data['status'],status);self.assertEqual(data['networkType'],network)
            m=hub.db.session.get(hub.Member,data['id']);self.assertFalse(m.alumni_bridge_enabled)
            # Reuse only the isolated fixture session to check routing, no real invitation.
            account=hub.UserAccount.query.filter_by(member_id=self.ids['active']).first();account.member_id=m.id;hub.db.session.commit()
            me=self.client.get('/api/auth/me',headers=self.headers['active']).get_json()['member']
            self.assertEqual(me['environment'],environment)
            account.member_id=self.ids['active'];hub.db.session.commit()
        self.assertEqual(hub.UserAccount.query.count(),before)
    def test_creation_rejects_conflicting_classification_and_unauthorized_requests(self):
        count=hub.Member.query.count()
        for data in [{'memberType':'BNI','status':'OFF'},{'memberType':'ALUMNI','networkType':'OFFICIAL_BNI'},{'memberType':'X'}]:
            r=self.post('members',dict(firstName='Bad',lastName='Data',**data));self.assertEqual(r.status_code,400)
        self.assertEqual(hub.Member.query.count(),count)
        self.assertEqual(self.post('members',{'firstName':'No','lastName':'Rights','memberType':'ALUMNI'},'active').status_code,403)
    def test_preview_and_name_only_import_for_both_spaces(self):
        for kind in ['BNI','ALUMNI']:
            wb=Workbook();wb.active.append(['Nom','Prénom']);wb.active.append(['Imported',kind]);out=io.BytesIO();wb.save(out);out.seek(0)
            r=self.client.post('/api/members/import/preview',headers=self.headers['admin'],data={'memberType':kind,'file':(out,'test.xlsx')})
            self.assertEqual(r.status_code,200);preview=r.get_json();self.assertEqual(preview['errors'],[])
            data={'memberType':kind,'rows':preview['rows']}
            r=self.post('members/import/confirm',data);self.assertEqual(r.status_code,200,r.get_json());self.assertEqual(r.get_json()['created'],1)
            m=hub.Member.query.filter_by(first_name=kind,last_name='Imported').one();mid=m.id
            self.assertIsNone(m.email);self.assertIsNone(m.user_account)
            self.assertEqual(hub.Membership.query.filter_by(member_id=mid).one().status,'OFF' if kind=='ALUMNI' else 'ACTIVE')
            self.assertEqual(self.post('members/import/confirm',data).get_json()['updated'],1)
            self.assertEqual(hub.Member.query.filter_by(first_name=kind,last_name='Imported').one().id,mid)
    def test_import_is_atomic_and_cannot_bypass_space_transitions(self):
        count=hub.Member.query.count()
        for kind,name in [('ALUMNI','active'),('BNI','off')]:
            r=self.post('members/import/confirm',{'memberType':kind,'rows':[{'firstName':'New','lastName':'NotCreated'},{'firstName':name,'lastName':'Test','existingId':9999}]})
            self.assertEqual(r.status_code,400,r.get_json());self.assertEqual(hub.Member.query.count(),count)
        for rows in [[{'firstName':'Same','lastName':'Name'}]*2,[{'firstName':'Other','lastName':'Name','email':'admin@example.test'}],[{'firstName':'New','lastName':'X','status':'OFF'}]]:
            self.assertEqual(self.post('members/import/confirm',{'memberType':'BNI','rows':rows}).status_code,400)
        self.assertEqual(hub.Member.query.count(),count)
    def test_existing_former_reuses_identity_and_preserves_membership_history(self):
        mid=self.ids['former'];old=hub.Membership.query.filter_by(member_id=mid).one();old_id=old.id
        r=self.post('members/import/confirm',{'memberType':'ALUMNI','rows':[{'firstName':'former','lastName':'Test'}]})
        self.assertEqual(r.status_code,200,r.get_json())
        self.assertEqual(hub.db.session.get(hub.Membership,old_id).status,'FORMER')
        self.assertEqual([m.status for m in hub.Membership.query.filter_by(member_id=mid).order_by(hub.Membership.id)],['FORMER','OFF'])
        self.assertEqual(hub.db.session.get(hub.Member,mid).network_type,'OFF')
