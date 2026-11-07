"""Shared monthly agenda and event publication across both active environments."""
import io
import unittest
from datetime import datetime, timedelta, time
from test_member_front import hub
import test_member_front as fixture

class SharedAgendaTests(unittest.TestCase):
    def setUp(self):
        fixture.MemberFrontTests.setUp(self)
        self.today=datetime.now(hub.ZoneInfo('Europe/Brussels')).date()
        for member in hub.Member.query.all():member.alumni_bridge_enabled=False
        hub.db.session.commit()
    def tearDown(self):fixture.MemberFrontTests.tearDown(self)
    def agenda(self,who='active',month=None):
        return self.client.get('/api/agenda?month='+(month or self.today.strftime('%Y-%m')),headers=self.headers[who])
    def event(self,who='active',**extra):
        data={'type':'EVENT','title':'Porte ouverte','message':'Bienvenue à tous','eventDate':self.today.isoformat(),'eventTime':'18:30','eventLocation':'Lieu public'}
        data.update(extra)
        return self.client.post('/api/me/requests',headers=self.headers[who],json=data)
    def test_both_environments_publish_and_receive_without_business_bridge(self):
        for who in ['active','off']:
            r=self.event(who);self.assertEqual(r.status_code,201,r.get_json())
        for who in ['active','off','admin']:
            data=self.agenda(who).get_json()
            self.assertEqual(len(data['items']),2)
            self.assertEqual({x['origin'] for x in data['items']},{'MEMBERS','ALUMNI'})
            self.assertEqual(data['items'][0]['startTime'],'18:30')
            self.assertEqual(data['items'][0]['location'],'Lieu public')
        for who in ['active','off']:
            notes=hub.Notification.query.filter_by(member_id=self.ids[who],type='SHARED_EVENT').all()
            self.assertEqual(len(notes),1)
            self.assertEqual(notes[0].link,'agenda:'+self.today.strftime('%Y-%m'))
        self.assertEqual(hub.Notification.query.filter_by(member_id=self.ids['former'],type='SHARED_EVENT').count(),0)
        self.assertEqual(self.client.post('/api/me/requests',headers=self.headers['off'],json={'type':'COMMUNICATION','message':'Private'}).status_code,403)
    def test_unauthenticated_inactive_and_invalid_month_are_rejected(self):
        self.assertEqual(self.client.get('/api/agenda').status_code,401)
        self.assertEqual(self.agenda('former').status_code,403)
        self.assertEqual(self.agenda(month='garbage').status_code,400)
        self.assertEqual(self.agenda(month='2026-13').status_code,400)
        self.assertEqual(self.event('off',eventDate='').status_code,400)
        self.assertEqual(self.event('off',eventTime='25:00').status_code,400)
        self.assertEqual(hub.MemberRequest.query.count(),0)
    def test_month_filter_and_meeting_privacy(self):
        first=self.today.replace(day=1)
        end=(first.replace(day=28)+timedelta(days=4)).replace(day=1)
        hub.db.session.add_all([
            hub.Meeting(date=first,start_time=time(7),type='REGULAR',status='PLANNED',location='Salle',notes='Note interne privée'),
            hub.Meeting(date=end,type='REGULAR',status='PLANNED'),
            hub.MemberRequest(member_id=self.ids['active'],type='COMMUNICATION',event_date=first,message='Confidentiel'),
            hub.MemberRequest(member_id=self.ids['off'],type='EVENT',event_date=end,title='Mois suivant'),
            hub.MemberRequest(member_id=self.ids['active'],type='EVENT',title='Sans date historique')])
        hub.db.session.commit()
        result=self.agenda('off');data=result.get_json();self.assertEqual(len(data['items']),1)
        self.assertEqual(data['items'][0]['location'],'Salle')
        self.assertNotIn('Note interne privée',result.get_data(as_text=True))
        self.assertNotIn('Confidentiel',result.get_data(as_text=True))
        self.assertIsNone(data['nextRole'])
        self.assertEqual(self.client.get('/api/meetings',headers=self.headers['off']).status_code,403)
    def test_next_role_includes_future_published_team_even_outside_selected_month(self):
        day=self.today+timedelta(days=35)
        meeting=hub.Meeting(date=day,start_time=time(7),type='REGULAR',status='PLANNED')
        duty=hub.Duty(code='WELCOME',name='Préparation de salle')
        hub.db.session.add_all([meeting,duty]);hub.db.session.flush()
        for who,status in [('active','PUBLISHED'),('admin','PUBLISHED'),('former','DRAFT')]:
            hub.db.session.add(hub.DutyAssignment(meeting_id=meeting.id,duty_id=duty.id,member_id=self.ids[who],status=status))
        hub.db.session.commit()
        role=self.agenda().get_json()['nextRole']
        self.assertEqual(role['date'],day.isoformat())
        self.assertEqual(role['duties'][0]['duty'],'Préparation de salle')
        self.assertEqual([a['memberId'] for a in role['team']],[self.ids['admin']])
        self.assertIsNone(self.agenda('off').get_json()['nextRole'])
    def test_shared_event_attachment_is_visible_but_private_requests_stay_private(self):
        r=self.client.post('/api/me/requests',headers=self.headers['off'],data={'type':'EVENT','title':'Drink','eventDate':self.today.isoformat(),'attachment':(io.BytesIO(b'event-pdf'),'invite.pdf')},content_type='multipart/form-data')
        self.assertEqual(r.status_code,201,r.get_json());rid=r.get_json()['id']
        self.assertEqual(self.client.get(f'/api/member-requests/{rid}/attachment',headers=self.headers['active']).data,b'event-pdf')
        hub.db.session.add(hub.MemberRequest(member_id=self.ids['active'],type='COMMUNICATION',attachment_data=b'private',attachment_name='private.pdf'));hub.db.session.commit()
        private=hub.MemberRequest.query.filter_by(type='COMMUNICATION').one()
        self.assertEqual(self.client.get(f'/api/member-requests/{private.id}/attachment',headers=self.headers['off']).status_code,403)
        self.assertEqual(self.client.get(f'/api/member-requests/{rid}/attachment',headers=self.headers['former']).status_code,403)
    def test_special_group_dates_notify_alumni_with_activated_accounts(self):
        off=hub.UserAccount.query.filter_by(member_id=self.ids['off']).one()
        r=self.client.post('/api/meetings',headers=self.headers['admin'],json={'date':self.today.isoformat(),'type':'SPECIAL','location':'Conférence'})
        self.assertEqual(r.status_code,201,r.get_json())
        self.assertEqual(hub.Notification.query.filter_by(member_id=off.member_id,type='SHARED_EVENT').count(),1)
