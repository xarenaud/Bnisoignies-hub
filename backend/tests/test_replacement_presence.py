"""Replacement delivery and meeting presence regressions, isolated data and mocked SMTP."""
import os
import unittest
from datetime import date,timedelta,time
from unittest.mock import patch
from test_member_front import hub
import test_alumni_spaces as fixture

class ReplacementPresenceTests(unittest.TestCase):
    add_member=fixture.AlumniSpacesTests.add_member
    get=fixture.AlumniSpacesTests.get
    post=fixture.AlumniSpacesTests.post
    def setUp(self):
        fixture.AlumniSpacesTests.setUp(self)
        self.day=date.today()+timedelta(days=7)
        self.meeting=hub.Meeting(date=self.day,start_time=time(7),type='REGULAR',status='PLANNED',location='Salle',notes='Note privée')
        hub.db.session.add(self.meeting);hub.db.session.flush()
        self.offer=hub.AlumniAvailability(member_id=self.ids['off'],date=self.day)
        hub.db.session.add(self.offer);hub.db.session.flush()
        self.booking=hub.AlumniSubstitution(official_id=self.ids['active'],alumni_id=self.ids['off'],availability_id=self.offer.id,date=self.day,status='REQUESTED')
        hub.db.session.add(self.booking);hub.db.session.commit()
    def tearDown(self):fixture.AlumniSpacesTests.tearDown(self)
    def accept(self):
        return self.client.patch(f'/api/alumni-space/substitutions/{self.booking.id}',headers=self.headers['off'],json={'status':'ACCEPTED'})
    def test_only_confirmed_substitutes_appear_on_home_and_selected_meeting(self):
        path=f'/api/agenda/meetings/{self.meeting.id}'
        self.assertEqual(self.client.get(path).status_code,401)
        self.assertEqual(self.get(path,'former').status_code,403)
        self.assertEqual(self.get(path,'off').status_code,403)
        self.assertEqual(self.get('/api/me/home').get_json()['nextMeeting']['guests'],[])
        self.assertEqual(self.accept().status_code,200)
        expected=self.get('/api/me/home').get_json()['nextMeeting']['guests']
        self.assertEqual(len(expected),1);self.assertEqual(expected[0]['replaces'],'active Test')
        self.assertEqual(expected[0]['kind'],'SUBSTITUTE')
        self.assertEqual(self.get(path).get_json()['guests'],expected)
        self.assertNotIn('notes',self.get(path,'off').get_json())
        self.assertEqual(self.get(path,'off2').status_code,403)
        hub.db.session.add(hub.AlumniReplacementNeed(official_id=self.ids['active'],alumni_id=self.ids['off'],date=self.day,status='ACCEPTED'));hub.db.session.commit()
        self.assertEqual(len(self.get(path).get_json()['guests']),1)
        self.assertEqual(hub.NetworkVisitor.query.count(),0) # No phantom business guest statistic.
        self.meeting.status='CANCELLED';hub.db.session.commit()
        self.assertEqual(self.get(path).get_json()['guests'],[])
    def test_request_and_confirmation_notify_both_parties_and_committee(self):
        hub.db.session.delete(self.booking)
        self.add_member('amelie','ACTIVE','OFFICIAL_BNI')
        hub.db.session.add(hub.GuestVisitReviewer(key='amelie',member_id=self.ids['amelie']));hub.db.session.commit()
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false'}),patch.object(hub.smtplib,'SMTP') as smtp:
            requested=self.post('/api/alumni-space/substitutions',{'availabilityId':self.offer.id})
            self.assertEqual(requested.status_code,201)
            self.assertEqual(requested.get_json()['status'],'REQUESTED')
            self.assertEqual({c.args[0]['To'] for c in smtp.return_value.send_message.call_args_list},{'active@example.test','off@example.test'})
            self.assertEqual({n.member_id for n in hub.Notification.query.filter_by(type='SUBSTITUTION_REQUEST')},{self.ids['active'],self.ids['off']})
            rid=requested.get_json()['id']
            self.assertEqual(self.client.patch(f'/api/alumni-space/substitutions/{rid}',headers=self.headers['off'],json={'status':'ACCEPTED'}).status_code,200)
            confirmed=hub.Notification.query.filter_by(type='SUBSTITUTION_ACCEPTED').all()
            self.assertEqual({n.member_id for n in confirmed},{self.ids['active'],self.ids['off'],self.ids['amelie']})
    def test_one_off_resend_is_durable_and_never_accepts_a_pending_request(self):
        self.booking.status='ACCEPTED'
        official=hub.db.session.get(hub.Member,self.ids['active']);official.first_name='Laurent';official.last_name='Sluys'
        alumni=hub.db.session.get(hub.Member,self.ids['off']);alumni.first_name='Jean François';alumni.last_name='CROHIN'
        otherday=self.day+timedelta(days=7)
        hub.db.session.add(hub.Meeting(date=otherday,type='REGULAR',status='PLANNED'))
        pending=hub.AlumniSubstitution(official_id=self.ids['active2'],alumni_id=self.ids['off'],availability_id=self.offer.id,date=otherday,status='REQUESTED')
        hub.db.session.add(pending);hub.db.session.commit()
        repair=hub.app.extensions['repair_replacement_notifications']
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false'}),patch.object(hub.smtplib,'SMTP') as smtp:
            report=repair();count=hub.Notification.query.count();mailcount=smtp.return_value.send_message.call_count
            self.assertEqual(report['confirmed'],1);self.assertEqual(report['requested'],1)
            self.assertEqual(report['jfLaurent'][0]['status'],'ACCEPTED')
            self.assertEqual(pending.status,'REQUESTED')
            self.assertEqual(report,repair());self.assertEqual(hub.Notification.query.count(),count)
            self.assertEqual(smtp.return_value.send_message.call_count,mailcount)
            self.assertEqual(hub.NotificationRepairRun.query.count(),1)
