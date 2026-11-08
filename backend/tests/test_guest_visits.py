import unittest,os
from datetime import date,timedelta,time
from unittest.mock import patch
from test_member_front import hub
import test_alumni_spaces as fixture
class GuestVisitTests(unittest.TestCase):
    add_member=fixture.AlumniSpacesTests.add_member
    post=fixture.AlumniSpacesTests.post
    get=fixture.AlumniSpacesTests.get
    bridge=fixture.AlumniSpacesTests.bridge
    def setUp(self):
        fixture.AlumniSpacesTests.setUp(self);self.day=date.today()+timedelta(days=7)
        for n in range(3):hub.db.session.add(hub.Meeting(date=self.day+timedelta(days=n),type='REGULAR',status='PLANNED',start_time=time(7)))
        for key,first,last in [('amelie','Amélie','Loedt'),('simon','Simon','Vanwymeersch')]:
            self.add_member(key,'ACTIVE','OFFICIAL_BNI');m=hub.db.session.get(hub.Member,self.ids[key]);m.first_name=first;m.last_name=last
        hub.db.session.add_all([hub.GuestVisitReviewer(key='amelie',member_id=self.ids['amelie']),hub.GuestVisitReviewer(key='simon',member_id=self.ids['simon'])]);hub.db.session.commit()
    def tearDown(self):fixture.AlumniSpacesTests.tearDown(self)
    def request_visit(self,n=0,**extra):return self.post('/api/alumni-visits',{'date':(self.day+timedelta(days=n)).isoformat(),'message':'Mon projet',**extra},'off')
    def decide(self,rid,status='APPROVED',who='amelie'):return self.client.patch(f'/api/alumni-visits/{rid}/decision',headers=self.headers[who],json={'status':status})
    def test_approval_is_required_and_only_named_reviewers_or_super_admin_can_validate(self):
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.test','SMTP_FROM':'hub@example.test','SMTP_USER':'','SMTP_SSL':'false'}),patch.object(hub.smtplib,'SMTP') as smtp:
            r=self.request_visit();self.assertEqual(r.status_code,201,r.get_json());rid=r.get_json()['id']
            self.assertEqual(hub.NetworkVisitor.query.count(),0)
            self.assertEqual({c.args[0]['To'] for c in smtp.return_value.send_message.call_args_list},{'amelie@example.test','simon@example.test'})
            hub.db.session.get(hub.Member,self.ids['amelie']).first_name='Responsable accueil'
            impostor=hub.db.session.get(hub.Member,self.ids['active']);impostor.first_name='Amélie';impostor.last_name='Loedt';hub.db.session.commit()
            self.assertEqual(self.decide(rid,who='active').status_code,403);self.assertEqual(self.decide(rid,who='off').status_code,403)
            r=self.decide(rid);self.assertEqual(r.status_code,200,r.get_json());self.assertEqual(hub.NetworkVisitor.query.count(),1)
            self.assertEqual(smtp.return_value.send_message.call_args.args[0]['To'],'off@example.test')
            self.assertEqual(self.decide(rid,who='simon').status_code,409)
            self.assertEqual(hub.NetworkVisitor.query.count(),1)
    def test_two_requests_per_mandate_including_withdrawals_and_refusals(self):
        r=self.request_visit();rid=r.get_json()['id']
        self.assertEqual(self.request_visit().status_code,200);self.assertEqual(hub.AlumniGuestVisit.query.count(),1)
        self.assertEqual(self.client.delete(f'/api/alumni-visits/{rid}',headers=self.headers['off']).status_code,200)
        r=self.request_visit(1);self.assertEqual(r.status_code,201);self.assertEqual(self.decide(r.get_json()['id'],'DECLINED','admin').status_code,200)
        self.assertEqual(self.request_visit(2).status_code,409);self.assertEqual(hub.NetworkVisitor.query.count(),0)
    def test_conversion_and_confirmed_replacement_protection(self):
        offer=hub.AlumniAvailability(member_id=self.ids['off'],date=self.day,active=True);hub.db.session.add(offer);hub.db.session.commit()
        self.assertEqual(self.request_visit(availabilityId=offer.id).status_code,201);self.assertFalse(offer.active)
        hub.db.session.add(hub.AlumniReplacementNeed(official_id=self.ids['active'],alumni_id=self.ids['off'],date=self.day+timedelta(days=1),status='ACCEPTED'));hub.db.session.commit()
        self.assertEqual(self.request_visit(1).status_code,409)
    def test_new_mandate_has_its_own_quota_and_approved_guest_cannot_be_reserved_as_substitute(self):
        rid=self.request_visit().get_json()['id'];self.assertEqual(self.decide(rid).status_code,200)
        self.assertEqual(self.request_visit(1).status_code,201)
        self.bridge();offer=hub.AlumniAvailability(member_id=self.ids['off'],date=self.day,active=True);hub.db.session.add(offer);hub.db.session.commit()
        self.assertEqual(self.post(f'/api/alumni-space/availability/{offer.id}/accept',{}).status_code,409)
        future=self.day+timedelta(days=60)
        hub.db.session.add_all([hub.Mandate(name='Suivante',start_date=future,end_date=future+timedelta(days=30)),hub.Meeting(date=future,type='REGULAR',status='PLANNED')]);hub.db.session.commit()
        self.assertEqual(self.post('/api/alumni-visits',{'date':future.isoformat()},'off').status_code,201)
