import unittest
from datetime import datetime,date,timedelta,time
from zoneinfo import ZoneInfo
from test_member_front import hub,MemberFrontTests
class PublicEventTests(MemberFrontTests):
    def test_events_follow_hub_edits_and_archive_by_brussels_day(self):
        today=datetime.now(ZoneInfo('Europe/Brussels')).date()
        event=hub.MemberRequest(member_id=self.ids['active'],type='EVENT',title='Visite publique',message='Présentation',event_date=today,event_time='07:00',event_location='Premier lieu',guest_email='private@example.test',attachment_data=b'private',status='COMPLETED')
        hub.db.session.add(event);hub.db.session.commit()
        data=self.client.get('/api/public/website').get_json()
        self.assertEqual(len(data['events']),1);self.assertEqual(data['pastEvents'],[])
        self.assertEqual(set(data['events'][0]),{'title','description','date','startTime','location','url'})
        event.title='Titre corrigé';event.event_location='Nouveau lieu';event.event_date=today-timedelta(days=1);hub.db.session.commit()
        response=self.client.get('/api/public/website');data=response.get_json()
        self.assertEqual(data['events'],[]);self.assertEqual(data['pastEvents'][0]['title'],'Titre corrigé');self.assertEqual(data['pastEvents'][0]['location'],'Nouveau lieu')
        self.assertNotIn('private',str(data));self.assertEqual(response.headers['Cache-Control'],'no-store')
        event.event_date=today+timedelta(days=2);hub.db.session.commit()
        data=self.client.get('/api/public/website').get_json();self.assertEqual(len(data['events']),1);self.assertEqual(data['pastEvents'],[])
    def test_special_meetings_sync_but_regular_and_cancelled_are_not_events(self):
        today=datetime.now(ZoneInfo('Europe/Brussels')).date()
        for kind,status,offset in [('HOSTED','PLANNED',-2),('JOINT','PLANNED',3),('REGULAR','PLANNED',2),('SPECIAL','CANCELLED',5)]:hub.db.session.add(hub.Meeting(type=kind,status=status,date=today+timedelta(days=offset),location='Lieu',notes='PRIVATE NOTES'))
        hub.db.session.commit();data=self.client.get('/api/public/website').get_json()
        self.assertEqual(len(data['events']),1);self.assertEqual(len(data['pastEvents']),1);self.assertNotIn('PRIVATE NOTES',str(data))
    def test_existing_public_visit_follows_its_linked_hub_meeting(self):
        today=datetime.now(ZoneInfo('Europe/Brussels')).date()
        event=hub.MemberRequest(member_id=self.ids['active'],type='EVENT',title='Visite',event_date=today,event_location='Old',status='COMPLETED')
        meeting=hub.Meeting(date=today+timedelta(days=4),type='HOSTED',location='Updated',status='PLANNED')
        hub.db.session.add_all([event,meeting]);hub.db.session.flush();hub.db.session.add(hub.PublicEventMeetingLink(event_id=event.id,meeting_id=meeting.id));hub.db.session.commit()
        data=self.client.get('/api/public/website').get_json()
        self.assertEqual(len(data['events']),1);self.assertEqual(data['events'][0]['date'],meeting.date.isoformat());self.assertEqual(data['events'][0]['location'],'Updated')
        meeting.date=today-timedelta(days=1);hub.db.session.commit()
        data=self.client.get('/api/public/website').get_json();self.assertEqual(data['events'],[]);self.assertEqual(len(data['pastEvents']),1)
        meeting.status='CANCELLED';hub.db.session.commit()
        data=self.client.get('/api/public/website').get_json();self.assertEqual(data['pastEvents'],[])
