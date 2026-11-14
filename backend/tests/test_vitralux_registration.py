import os,unittest
from unittest.mock import patch,MagicMock
from test_member_front import hub
class VitraluxRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.app=hub.create_app();self.client=self.app.test_client();self.origin={'Origin':'https://www.bim-soignies.be'}
        self.data={'firstName':'Visiteur','lastName':'Test','email':'visitor@example.test','company':'Bureau test','consent':True}
    def post(self,data=None,headers=None):return self.client.post('/api/public/vitralux-registration',json=data or self.data,headers=self.origin if headers is None else headers)
    def test_valid_request_goes_only_to_hub(self):
        smtp=MagicMock();smtp.send_message.return_value={}
        with patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_FROM':'hub@bim-soignies.be','SMTP_STARTTLS':'false','SMTP_USER':''}),patch.object(hub.smtplib,'SMTP',return_value=smtp):
            response=self.post({**self.data,'recipient':'attacker@example.test'})
        self.assertEqual(response.status_code,201)
        msg=smtp.send_message.call_args.args[0]
        self.assertEqual(msg['To'],'hub@bim-soignies.be');self.assertIn('19/11/2026',msg['Subject'])
        self.assertIn('visitor@example.test',msg.get_content());self.assertEqual(response.headers['Access-Control-Allow-Origin'],'https://www.bim-soignies.be')
        self.assertEqual(self.post().status_code,429)
    def test_missing_consent_bad_email_and_honeypot_are_rejected(self):
        for edit in [{'consent':False},{'email':'bad'},{'website':'spam'},{'firstName':''}]:self.assertEqual(self.post({**self.data,**edit}).status_code,400)
        self.assertEqual(self.post(headers={'Origin':'https://evil.example'}).status_code,403)
    def test_mail_unavailable_is_never_reported_as_success(self):
        with patch.dict(os.environ,{'SMTP_HOST':''}):self.assertEqual(self.post().status_code,503)
    def test_preflight_supports_browser_form(self):
        response=self.client.options('/api/public/vitralux-registration',headers={**self.origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'})
        self.assertEqual(response.status_code,200);self.assertEqual(response.headers['Access-Control-Allow-Origin'],'https://www.bim-soignies.be')
