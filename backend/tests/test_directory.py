"""Directory visibility checks against isolated fixtures, without real contacts or mail."""
import unittest
from test_member_front import hub
import test_alumni_spaces as fixture

class DirectoryTests(unittest.TestCase):
    add_member=fixture.AlumniSpacesTests.add_member
    get=fixture.AlumniSpacesTests.get
    post=fixture.AlumniSpacesTests.post
    bridge=fixture.AlumniSpacesTests.bridge
    encode_all=fixture.AlumniSpacesTests.encode_all
    def setUp(self):fixture.AlumniSpacesTests.setUp(self)
    def tearDown(self):fixture.AlumniSpacesTests.tearDown(self)
    def ids_in_directory(self,who='active',query=''):
        response=self.get('/api/directory'+query,who)
        self.assertEqual(response.status_code,200,response.get_json())
        return {row['id'] for row in response.get_json()}

    def test_official_directory_needs_no_business_bridge_and_contains_only_eligible_contacts(self):
        self.assertEqual(self.client.get('/api/directory').status_code,401)
        self.assertEqual(self.get('/api/directory','former').status_code,403)
        expected={self.ids[k] for k in ['active','active2','admin','off','off2']}
        self.assertEqual(self.ids_in_directory(),expected)
        self.assertIsNone(self.get('/api/me/home').get_json()['offActivity'])
        self.encode_all('active','off',403)
        for status in ['INVITED','DISABLED','SUSPENDED']:
            member=hub.db.session.get(hub.Member,self.ids['off2']);member.user_account.status=status;hub.db.session.commit()
            self.assertNotIn(member.id,self.ids_in_directory())
        # Official members imported before their account activation remain in their group's directory.
        self.add_member('new_member','ONBOARDING','OFFICIAL_BNI')
        member=hub.db.session.get(hub.Member,self.ids['new_member']);member.user_account.status='INVITED';hub.db.session.commit()
        self.assertIn(member.id,self.ids_in_directory())

    def test_alumni_cannot_bypass_personal_consent_with_queries_or_admin_status(self):
        alumni={self.ids['off'],self.ids['off2']}
        self.assertEqual(self.ids_in_directory('off'),alumni)
        self.bridge('active')
        self.assertEqual(self.ids_in_directory('off'),alumni|{self.ids['active']})
        self.bridge('active',False)
        self.assertEqual(self.ids_in_directory('off','?memberId='+str(self.ids['active'])+'&environment=MEMBERS'),alumni)
        hub.db.session.get(hub.Member,self.ids['off']).user_account.is_system_admin=True;hub.db.session.commit()
        self.assertEqual(self.ids_in_directory('off'),alumni)
        self.bridge('active')
        hub.db.session.get(hub.Member,self.ids['active']).user_account.status='DISABLED';hub.db.session.commit()
        self.assertNotIn(self.ids['active'],self.ids_in_directory('off'))

    def test_response_exposes_contact_fields_without_account_or_admin_data(self):
        member=hub.db.session.get(hub.Member,self.ids['active2'])
        member.company='Société exemple';member.activity='Électricité';member.phone='+32 470 00 00 00';hub.db.session.commit()
        row=next(x for x in self.get('/api/directory').get_json() if x['id']==member.id)
        self.assertEqual(set(row),{'id','firstName','lastName','company','activity','phone','email','category'})
        self.assertEqual(row['category'],'MEMBERS');self.assertEqual(row['phone'],member.phone)
        self.assertEqual(row['email'],'active2@example.test')
        self.assertEqual(next(x for x in self.get('/api/directory').get_json() if x['id']==self.ids['off'])['category'],'ALUMNI')
