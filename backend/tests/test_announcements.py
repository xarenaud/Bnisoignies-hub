import unittest
from datetime import date,timedelta,datetime
from test_member_front import hub
import test_alumni_spaces as fixture
class AnnouncementTests(unittest.TestCase):
    add_member=fixture.AlumniSpacesTests.add_member
    def setUp(self):fixture.AlumniSpacesTests.setUp(self);self.today=datetime.now(hub.ZoneInfo('Europe/Brussels')).date()
    def tearDown(self):fixture.AlumniSpacesTests.tearDown(self)
    def post(self,who='off',**data):return self.client.post('/api/announcements',headers=self.headers[who],json={'date':self.today.isoformat(),'durationDays':1,'subject':'Je recherche un stagiaire','description':'Communication',**data})
    def interest(self,rid,state=True,who='active'):return self.client.put(f'/api/announcements/{rid}/interest',headers=self.headers[who],json={'interested':state})
    def test_members_and_alumni_publish_without_bridge_and_notify_only_author(self):
        r=self.post();self.assertEqual(r.status_code,201,r.get_json());rid=r.get_json()['id']
        self.assertEqual(len(self.client.get('/api/announcements',headers=self.headers['active']).get_json()),1)
        self.assertEqual(self.interest(rid).status_code,200);self.assertEqual(self.interest(rid).status_code,200)
        notices=hub.Notification.query.filter_by(type='ANNOUNCEMENT_INTEREST').all();self.assertEqual(len(notices),1);self.assertEqual(notices[0].member_id,self.ids['off']);self.assertIn('active Test',notices[0].title)
        self.assertEqual(self.interest(rid,False).get_json()['interestCount'],0)
        self.assertEqual(self.interest(rid,True,'off').status_code,403)
        self.assertEqual(self.post('active').status_code,201)
    def test_date_duration_expiry_and_permissions(self):
        self.assertEqual(self.post(durationDays=0).status_code,400)
        self.assertEqual(self.post(durationDays=32).status_code,400)
        self.assertEqual(self.post(date='2027-02-01',durationDays=29).status_code,400)
        self.assertEqual(self.post('former').status_code,403)
        self.assertEqual(self.client.get('/api/announcements').status_code,401)
        rid=self.post().get_json()['id'];row=hub.db.session.get(hub.Announcement,rid);row.end_date=self.today;hub.db.session.commit()
        self.assertEqual(self.client.get('/api/announcements',headers=self.headers['active']).get_json(),[])
        self.assertEqual(self.interest(rid).status_code,404)
    def test_only_author_can_withdraw_and_withdrawal_hides_news(self):
        rid=self.post().get_json()['id']
        self.assertEqual(self.client.delete(f'/api/announcements/{rid}',headers=self.headers['active']).status_code,403)
        self.assertEqual(self.client.delete(f'/api/announcements/{rid}',headers=self.headers['off']).status_code,200)
        self.assertEqual(self.client.get('/api/announcements',headers=self.headers['active']).get_json(),[])
    def test_future_news_is_only_previewed_by_its_author(self):
        self.assertEqual(self.post(date=(self.today+timedelta(days=1)).isoformat()).status_code,201)
        self.assertEqual(self.client.get('/api/announcements',headers=self.headers['active']).get_json(),[])
        self.assertEqual(len(self.client.get('/api/announcements',headers=self.headers['off']).get_json()),1)
