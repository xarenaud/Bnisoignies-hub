"""Public site projection must exclude alumni and confidential fields."""
import unittest
from datetime import date,timedelta,time
from test_member_front import hub,MemberFrontTests
class PublicWebsiteTests(MemberFrontTests):
    def test_public_projection_is_minimal_and_excludes_alumni(self):
        response=self.client.get('/api/public/website',headers={'Origin':'https://www.bim-soignies.be'})
        self.assertEqual(response.status_code,200)
        data=response.get_json()
        self.assertEqual({x['firstName'] for x in data['members']},{'active','admin'})
        self.assertEqual(set(data['members'][0]),{'firstName','lastName','company','activity'})
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'),'https://www.bim-soignies.be')
        member=hub.db.session.get(hub.Member,self.ids['active']);member.user_account.status='SUSPENDED';hub.db.session.commit()
        self.assertEqual({x['firstName'] for x in self.client.get('/api/public/website').get_json()['members']},{'admin'})
    def test_only_upcoming_meetings_without_private_notes(self):
        for offset,status,kind in [(-1,'PLANNED','REGULAR'),(1,'PLANNED','REGULAR'),(2,'CANCELLED','REGULAR'),(3,'PLANNED','NO_MEETING')]:
            hub.db.session.add(hub.Meeting(date=date.today()+timedelta(days=offset),status=status,type=kind,start_time=time(7),location='Lieu public',notes='PRIVATE'))
        hub.db.session.commit()
        data=self.client.get('/api/public/website').get_json()
        self.assertEqual(len(data['meetings']),1)
        self.assertNotIn('notes',data['meetings'][0])
        self.assertNotIn('PRIVATE',str(data))
