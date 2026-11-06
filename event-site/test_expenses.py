import os,tempfile,unittest,importlib.util,base64,json,sys,io
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pypdf import PdfReader
import expense_notes

class ExpensesTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();os.environ.update(BNI_EVENT_DATA_DIR=self.tmp.name,BNI_EVENT_ADMIN_PASSWORD='test',BNI_EVENT_NOTIFICATIONS_ENABLED='false')
  s=importlib.util.spec_from_file_location('expenseapp',Path(__file__).with_name('app.py'));self.m=importlib.util.module_from_spec(s);sys.modules['expenseapp']=self.m;s.loader.exec_module(self.m)
  self.c=self.m.app.test_client();self.ref='BNI-AAAAAAAAAA';self.base='/admin/inscriptions/'+self.ref+'/note';self.headers={'Authorization':'Basic '+base64.b64encode(b'bni:test').decode()}
  payload={'firstName':'Élodie','lastName':'Dupont','group':'Soignies','email':'participant@example.org','phone':'0470123456','guests':[],'invoiceRequested':True,'vatNumber':'BE0123456789'}
  with self.m.database() as db:db.execute('INSERT INTO registrations(reference,fingerprint,payload,count,total,created_at,is_test) VALUES(?,?,?,?,?,?,?)',(self.ref,'fixture',json.dumps(payload),1,15,'2026-11-06T12:00:00+01:00',0))
 def tearDown(self):self.tmp.cleanup()
 def post(self,action,**data):
  import hmac,hashlib
  data['token']=hmac.new(b'test',('expense:'+self.ref+':'+action).encode(),hashlib.sha256).hexdigest()
  return self.c.post(self.base+'/'+action,data=data,headers=self.headers)
 def test_workflow(self):
  self.assertEqual(self.c.get(self.base).status_code,401)
  self.assertEqual(self.c.get('/admin/inscriptions/'+self.ref+'/note.pdf').status_code,401)
  self.assertEqual(self.c.get(self.base,headers=self.headers).status_code,200)
  draft=self.c.get('/admin/inscriptions/'+self.ref+'/note.pdf',headers=self.headers).data
  text=' '.join(p.extract_text() for p in PdfReader(io.BytesIO(draft)).pages)
  self.assertIn('BROUILLON',text);self.assertNotIn('déclare avoir reçu',text)
  self.assertEqual(self.post('send').status_code,409)
  self.assertEqual(self.c.post(self.base+'/payment',data={},headers=self.headers).status_code,403)
  self.assertEqual(self.post('company',companyName='Société Exemple SRL',companyAddress='Rue du Test 12\n7000 Mons').status_code,303)
  self.assertEqual(self.post('payment',amount='10',paymentDate='2026-11-06',confirmed='yes').status_code,422)
  self.assertEqual(self.post('payment',amount='15',paymentDate='2026-11-06',confirmed='yes',bankReference='VIREMENT-001').status_code,303)
  final=self.c.get('/admin/inscriptions/'+self.ref+'/note.pdf',headers=self.headers).data
  text=' '.join(p.extract_text() for p in PdfReader(io.BytesIO(final)).pages)
  for required in ['déclare avoir reçu','15,00 EUR','Société Exemple','Casteau','Association de fait']:self.assertIn(required,text)
  self.assertNotIn('BROUILLON',text)
  self.assertEqual(self.post('company',companyName='Changed',companyAddress='Changed').status_code,409)
  # Repeated validation leaves final PDF and original payment metadata intact.
  self.post('payment',amount='15',paymentDate='2026-11-06',confirmed='yes',bankReference='OTHER')
  self.assertEqual(final,self.c.get('/admin/inscriptions/'+self.ref+'/note.pdf',headers=self.headers).data)
  sent=[]
  with patch('expense_notes.EmailMessage',wraps=expense_notes.EmailMessage):
   # Installed route captures sender callable; mock its SMTP transport instead.
   class SMTP:
    def __enter__(s):return s
    def __exit__(s,*a):pass
    def starttls(s,**k):pass
    def login(s,*a):pass
    def send_message(s,msg):sent.append(msg);return {}
   with patch.dict(os.environ,{'SMTP_HOST':'mock','SMTP_FROM':'hub@bim-soignies.be'}),patch('smtplib.SMTP',return_value=SMTP()):
    self.assertEqual(self.post('send').status_code,303);self.post('send')
  self.assertEqual(len(sent),1);self.assertEqual(sent[0]['To'],'participant@example.org')
  self.assertEqual(list(sent[0].iter_attachments())[0].get_payload(decode=True),final)
  self.assertIn(b'Pay',self.c.get('/admin/inscriptions',headers=self.headers).data)
  self.assertIn(b'Pay',self.c.get('/admin/inscriptions.csv',headers=self.headers).data)
  self.assertEqual(self.c.get('/admin/inscriptions.xlsx',headers=self.headers).status_code,200)
  Path(self.tmp.name,'final.pdf').write_bytes(final)
 def test_lookup_and_no_invented_company(self):
  with patch('expense_notes.urllib.request.urlopen',side_effect=TimeoutError):
   name,address,status=expense_notes.company_lookup('BE0123456789')
  self.assertEqual((name,address),('',''));self.assertIn('indisponible',status)
  class Reply:
   def __enter__(s):return s
   def __exit__(s,*a):pass
   def read(s,*a):return json.dumps({'valid':True,'name':'Official Company','address':'Official Address'}).encode()
  with patch('expense_notes.urllib.request.urlopen',return_value=Reply()):
   self.m.expense_service['prepare_pending']()
  with self.m.database() as db:n=db.execute('SELECT * FROM expense_notes WHERE reference=?',(self.ref,)).fetchone()
  self.assertEqual(n['company_name'],'Official Company');self.assertTrue(n['draft_pdf']);self.assertIsNone(n['paid_at']);self.assertIsNone(n['final_pdf'])

if __name__=='__main__':unittest.main()
