const test=require('node:test');const assert=require('node:assert/strict');const {JSDOM}=require('jsdom');const esbuild=require('esbuild');const path=require('node:path');
let bundle;
const wait=()=>new Promise(r=>setTimeout(r,60));
async function mount(environment='MEMBERS',admin=false,url='https://hub.test/',initialAuthOffline=false){
 if(!bundle){const r=await esbuild.build({entryPoints:[path.join(__dirname,'../src/main.jsx')],bundle:true,write:false,format:'iife',loader:{'.css':'empty'},define:{'import.meta.env.VITE_API_URL':'"https://hub.test/api"','import.meta.env.PROD':'false'}});bundle=r.outputFiles[0].text;}
 const dom=new JSDOM('<div id="root"></div>',{url,runScripts:'dangerously'}),w=dom.window;const errors=[];w.addEventListener('error',e=>errors.push(e.message));w.localStorage.setItem('bni_token','fixture');w.confirm=()=>true;
 const calls=[];let opted=false;let needs=environment==='ALUMNI'?[{id:9,date:'2099-02-05',official:'Membre actif',officialId:2,status:'OPEN',note:'Remplacement demandé'}]:[];const user=()=>({id:1,firstName:'Test',lastName:'Membre',email:'fixture@example.test',environment,alumniBridgeEnabled:opted,networkModuleEnabled:environment==='ALUMNI'||opted,networkAccessEnabled:environment==='ALUMNI'||opted,roles:[],isAdmin:admin,isSystemAdmin:admin});
 w.fetch=async(url,options={})=>{calls.push({url,method:options.method||'GET'});const p=new URL(url).pathname.replace('/api','');let data=[];
  if(p==='/agenda'){const month=new URL(url).searchParams.get('month');data={month,items:[{id:'meeting-4',kind:'MEETING',date:month+'-05',startTime:'07:00',type:'REGULAR',location:'Salle du groupe'},{id:'event-1',kind:'EVENT',date:month+'-12',title:'Portes ouvertes du membre',member:'Membre actif',origin:'MEMBERS'},{id:'event-2',kind:'EVENT',date:month+'-19',title:'Conférence des anciens',member:'Ancien Test',origin:'ALUMNI'}],nextRole:environment==='ALUMNI'?null:{date:'2099-02-05',startTime:'07:00',duties:[{id:1,duty:'Préparation de salle',status:'PUBLISHED'}],team:[{id:2,member:'Collègue Accueil',duty:'Accueil des invités'}]}};}
  if(p==='/me/requests'&&options.method==='POST')data={id:8,emailSent:false};
  if(p==='/meetings')data=[{id:4,date:'2099-02-05',type:'REGULAR',status:'PLANNED',location:'Lieu de réunion'}];
  if(p==='/alumni-space/replacement-needs'){
   if(options.method==='POST'){const d=JSON.parse(options.body);needs=[{id:9,...d,official:'Membre actif',officialId:1,status:'OPEN'}];data={...needs[0],notifiedCount:1};}else data=needs;
  }
  if(p==='/alumni-space/replacement-needs/9'&&options.method==='POST'){needs=needs.map(n=>({...n,status:'ACCEPTED',alumni:'Test Membre',alumniId:1}));data=needs[0];}
  if(p==='/auth/me'){if(initialAuthOffline)throw new Error('offline');data={member:user()};}
  if(p==='/members/3/invite')data={activationUrl:'https://hub.test/?activate=fixture-invitation',emailSent:false,copyEmail:'hub@bim-soignies.be',copyEmailSent:false,expiresInHours:48};
  if(p==='/auth/activate')data={status:'ACTIVE'};
  if(p==='/members')data=[{id:2,firstName:'Actif',lastName:'Test',status:'ACTIVE',accountStatus:'ACTIVE',networkType:'OFFICIAL_BNI'},{id:3,firstName:'Ancien',lastName:'Test',status:'OFF',networkType:'OFF'}];
  if(p==='/me/notifications')data={unread:0,items:[]};
  if(p==='/me/home')data={nextMeeting:{date:'2099-02-05',type:'REGULAR',startTime:'07:00',assignments:[],guests:[{id:'guest-1',name:'Invité du jeudi',invitedBy:'Test Membre'}]},memberStats:null,groupStats:null,offActivity:{mandateId:1,mandate:'Mandature en cours',periodStart:'2026-10-01',periodEnd:'2026-11-08',businessGenerated:1250.5,businessReceived:375,oneToOnes:4,referralsGiven:7}};
  if(p==='/alumni-space/me')data={environment,bridgeEnabled:opted,requestedAt:null,stats:null};
  if(p==='/me/alumni-bridge'){opted=JSON.parse(options.body).enabled;data={member:user(),bridgeEnabled:opted};}
  if(p==='/network/config')data={features:{REFERRALS:true,BUSINESS:true,ONE_TO_ONE:true},fullNetworkEnabled:true};
  if(p==='/network/members')data=[{id:2,name:'Ancien autorisé',networkType:'OFF'}];
  if(p==='/me/profile')data={...user(),subscription:{label:'Forfait enregistré'}};
  if(p==='/me/past-stats')data={mandates:[],stats:null};
  if(p==='/off-membership/me')data={enabled:false};
  return {ok:true,json:async()=>data};
 };
 w.eval(bundle);await wait();await wait();
 const text=()=>w.document.body.textContent;
 const click=async label=>{const button=[...w.document.querySelectorAll('button')].find(b=>b.textContent===label);assert.ok(button,'Button: '+label);button.click();await wait();await wait();};
 return {w,errors,text,click,calls,close:()=>w.close()};
}
test('official UI only exposes business actions after personal consent',async()=>{const f=await mount();try{await f.click('Participer');assert.ok(f.text().includes('Envoyer une infomerciale'));assert.ok(![...f.w.document.querySelectorAll('button')].some(b=>b.textContent==='MPB'));await f.click('Profil');await f.click('J’active personnellement ma liaison');await f.click('Participer');assert.ok([...f.w.document.querySelectorAll('button')].some(b=>b.textContent==='MPB'));await f.click('Recommandations');assert.ok(f.text().includes('Ancien autorisé'));await f.click('Profil');await f.click('Désactiver ma liaison');await f.click('Participer');assert.ok(![...f.w.document.querySelectorAll('button')].some(b=>b.textContent==='MPB'));assert.deepEqual(f.errors,[]);}finally{f.close();}});
test('alumni UI has shared planning, exchanges and targeted substitutions',async()=>{const f=await mount('ALUMNI');try{assert.ok(f.text().includes('HUB Anciens'));const nav=[...f.w.document.querySelectorAll('nav button')].map(b=>b.textContent);assert.deepEqual(nav,['Accueil','Planning','Échanges','Suppléances','Profil']);assert.equal(f.w.document.querySelectorAll('nav button svg').length,5);assert.equal(f.w.document.querySelectorAll('.actions button svg').length,4);await f.click('Échanges');assert.ok(f.text().includes('Donner une recommandation'));await f.click('Suppléances');assert.ok(f.text().includes('Proposer ma disponibilité'));await f.click('Profil');assert.ok(f.text().includes('Votre espace Anciens'));assert.deepEqual(f.errors,[]);}finally{f.close();}});
test('inactive former member can request access without exposing the group',async()=>{const f=await mount('INACTIVE');try{assert.ok(f.text().includes('Demander mon passage chez les anciens'));assert.ok(!f.w.document.querySelector('nav'));assert.ok(!f.text().includes('Prochaine réunion'));assert.deepEqual(f.errors,[]);}finally{f.close();}});

test('admin entry and imports share one explicit destination',async()=>{const f=await mount('MEMBERS',true);try{await f.click('Ouvrir');const memberButton=[...f.w.document.querySelectorAll('button')].find(b=>b.querySelector('b')?.textContent==='Membres');assert.ok(memberButton);memberButton.click();await wait();await wait();await f.click(' Ajouter');const select=f.w.document.querySelector('select[name="memberType"]');assert.ok(select);assert.equal(select.options.length,2);assert.equal(f.w.document.querySelectorAll('form select').length,1);select.value='ALUMNI';select.dispatchEvent(new f.w.Event('change',{bubbles:true}));await wait();assert.ok(f.text().includes('Créer un ancien membre'));assert.ok(!f.text().includes('Actif Test'));assert.ok(f.text().includes('Ancien Test'));await f.click(' Importer des anciens');assert.ok(f.text().includes('Choisir la destination'));assert.equal(f.w.document.querySelector('select').value,'ALUMNI');assert.deepEqual(f.errors,[]);}finally{f.close();}});

test('inviting an alumnus displays the activation link without crashing',async()=>{const f=await mount('MEMBERS',true);try{await f.click('Ouvrir');[...f.w.document.querySelectorAll('button')].find(b=>b.querySelector('b')?.textContent==='Membres').click();await wait();await wait();await f.click('Anciens membres (1)');await f.click('Inviter');assert.deepEqual(f.errors,[]);assert.ok(f.text().includes('Invitation créée pour Ancien Test'));const link=f.w.document.querySelector('.inviteBox a');assert.equal(link?.href,'https://hub.test/?activate=fixture-invitation');assert.ok(f.text().includes('Copier le lien'));assert.ok(f.text().includes('La copie n’a pas pu être transmise à hub@bim-soignies.be'));}finally{f.close();}});
test('invitation URL opens password activation even when another session exists',async()=>{const f=await mount('MEMBERS',true,'https://hub.test/?activate=fixture-invitation');try{assert.ok(f.text().includes('Choisissez votre mot de passe'));const form=f.w.document.querySelector('form');form.elements.password.value='FixturePassword123';form.elements.confirm.value='FixturePassword123';form.dispatchEvent(new f.w.Event('submit',{bubbles:true,cancelable:true}));await wait();await wait();assert.ok(f.text().includes('Compte activé'));assert.deepEqual(f.errors,[]);}finally{f.close();}});

test('administrator no longer has a simulator or alumni preview',async()=>{const f=await mount('MEMBERS',true);try{assert.ok(!f.text().includes('Vue Ancien membre'));f.w.dispatchEvent(new f.w.Event('hub:preview-alumni'));await wait();assert.ok(!f.text().includes('Mode test'));assert.ok(!f.text().includes('E-mails de test'));assert.deepEqual(f.errors,[]);}finally{f.close();}});
test('member publishes an open need using production route and planned meeting',async()=>{const f=await mount();try{await f.click('Profil');await f.click('J’active personnellement ma liaison');await f.click('Participer');await f.click('Solliciter une suppléance');assert.ok(f.text().includes('Signaler un besoin de suppléance'));const form=f.w.document.querySelector('form');form.elements.date.value='2099-02-05';form.elements.note.value='Besoin de remplacement';form.dispatchEvent(new f.w.Event('submit',{bubbles:true,cancelable:true}));await wait();await wait();assert.ok(f.text().includes('Besoin publié'));assert.ok(f.calls.some(c=>c.url.endsWith('/alumni-space/replacement-needs')&&c.method==='POST'));assert.deepEqual(f.errors,[]);}finally{f.close();}});
test('alumnus opens email deep link and accepts via production route',async()=>{const f=await mount('ALUMNI',false,'https://hub.test/?substitutions=1');try{assert.ok(f.text().includes('Suppléances recherchées'));await f.click('Je m’engage à assurer la suppléance');assert.ok(f.text().includes('Test Membre a accepté de remplacer Membre actif le 2099-02-05.'));assert.ok(f.calls.some(c=>c.url.endsWith('/alumni-space/replacement-needs/9')&&c.method==='POST'));assert.deepEqual(f.errors,[]);}finally{f.close();}});

test('network failures and server errors preserve the logged-in session; 401 clears it',async()=>{const f=await mount();try{
 const normal=f.w.fetch;f.w.fetch=async(url,options)=>url.endsWith('/auth/me')?Promise.reject(new Error('offline')):normal(url,options);
 f.w.dispatchEvent(new f.w.Event('focus'));await wait();await wait();assert.equal(f.w.localStorage.getItem('bni_token'),'fixture');assert.ok(f.text().includes('Votre session est conservée.'));assert.ok(f.w.document.querySelector('nav'));
 f.w.fetch=async(url,options)=>url.endsWith('/auth/me')?{ok:false,status:503,json:async()=>({})}:normal(url,options);
 f.w.dispatchEvent(new f.w.Event('focus'));await wait();await wait();assert.equal(f.w.localStorage.getItem('bni_token'),'fixture');
 f.w.fetch=normal;f.w.dispatchEvent(new f.w.Event('online'));await wait();await wait();assert.ok(!f.text().includes('Votre session est conservée.'));
 f.w.fetch=async(url,options)=>url.endsWith('/auth/me')?{ok:false,status:401,json:async()=>({})}:normal(url,options);
 f.w.dispatchEvent(new f.w.Event('focus'));await wait();await wait();assert.equal(f.w.localStorage.getItem('bni_token'),null);assert.ok(!f.w.document.querySelector('nav'));assert.deepEqual(f.errors,[]);
}finally{f.close();}});

test('an offline app restart keeps its token and retries instead of asking for credentials',async()=>{const f=await mount('MEMBERS',false,'https://hub.test/',true);try{assert.equal(f.w.localStorage.getItem('bni_token'),'fixture');assert.ok(f.text().includes('Votre session est conservée.'));assert.ok(!f.w.document.querySelector('input[name="email"]'));const normal=f.w.fetch;f.w.fetch=async(url,options)=>url.endsWith('/auth/me')?{ok:true,json:async()=>({member:{id:1,firstName:'Test',lastName:'Membre',environment:'MEMBERS',roles:[]}})}:normal(url,options);await f.click('Réessayer la connexion');assert.ok(f.w.document.querySelector('nav'));assert.equal(f.w.localStorage.getItem('bni_token'),'fixture');assert.deepEqual(f.errors,[]);}finally{f.close();}});
test('personal bridge stays visible for every active role when secondary profile loading fails',async()=>{
 for(const admin of [false,true]){const f=await mount('MEMBERS',admin);try{
  const normal=f.w.fetch;f.w.fetch=async(url,options)=>url.endsWith('/alumni-space/me')?Promise.reject(new Error('temporary failure')):normal(url,options);
  await f.click('Profil');assert.ok(f.text().includes('Liaison personnelle avec les anciens'));assert.ok(f.text().includes('J’active personnellement ma liaison'));assert.ok(f.text().includes('Actualiser la liaison'));
  f.w.fetch=normal;await f.click('J’active personnellement ma liaison');assert.ok(f.text().includes('Désactiver ma liaison'));assert.deepEqual(f.errors,[]);
 }finally{f.close();}}
});

test('system admin enters real member assistance and restores original session without resetting password',async()=>{const f=await mount('MEMBERS',true);try{
 const normal=f.w.fetch;const writes=[];const target={id:2,firstName:'Actif',lastName:'Test',environment:'MEMBERS',roles:[],isAdmin:false,isSystemAdmin:false,supportSession:true,supportReadOnly:true,alumniBridgeEnabled:false};
 f.w.fetch=async(url,options={})=>{const p=new URL(url).pathname.replace('/api','');if(options.method&&options.method!=='GET')writes.push(p);
  if(p==='/system/support-sessions')return {ok:true,json:async()=>({token:'support-fixture',memberId:2})};
  if(p==='/system/support-sessions/stop')return {ok:true,json:async()=>({status:'ok'})};
  if(p==='/auth/me'&&options.headers?.Authorization==='Bearer support-fixture')return {ok:true,json:async()=>({member:target})};
  if(p==='/me/profile'&&options.headers?.Authorization==='Bearer support-fixture')return {ok:true,json:async()=>({...target,email:'actif@example.test',subscription:{label:'Forfait réel'}})};
  return normal(url,options);
 };
 await f.click('Ouvrir');[...f.w.document.querySelectorAll('button')].find(b=>b.querySelector('b')?.textContent==='Membres').click();await wait();await wait();await f.click('Voir comme ce membre');
 assert.ok(f.text().includes('Mode Doppelganger · Actif Test'));assert.equal(f.w.localStorage.getItem('bni_token'),'fixture');assert.equal(f.w.sessionStorage.getItem('hub_support_token'),'support-fixture');assert.ok(!f.text().includes('Voir comme membre'));
 await f.click('Profil');assert.ok(f.text().includes('Actif Test'));await f.click('Recevoir un lien de réinitialisation');assert.ok(f.text().includes('Aucun e-mail de réinitialisation envoyé.'));assert.ok(!writes.includes('/auth/forgot-password'));
 await f.click('Revenir à mon compte administrateur');assert.equal(f.w.localStorage.getItem('bni_token'),'fixture');assert.equal(f.w.sessionStorage.getItem('hub_support_token'),null);assert.ok(f.text().includes('Voir comme membre'));assert.ok(!f.text().includes('Mode Doppelganger ·'));assert.deepEqual(f.errors,[]);
}finally{f.close();}});

test('mail diagnostic displays the exact copy error without inviting a member',async()=>{const f=await mount('MEMBERS',true);try{const normal=f.w.fetch;const diagnostic=[];f.w.fetch=async(url,options={})=>{if(url.endsWith('/system/mail-test')){diagnostic.push(url);return {ok:true,json:async()=>({mailTest:true,copyEmail:'hub@bim-soignies.be',copyEmailSent:false,copyEmailError:{code:'RECIPIENT_REFUSED',smtpCode:550,message:'Destinataire refusé',detail:'Mailbox unavailable'}})}}return normal(url,options)};await f.click('Ouvrir');[...f.w.document.querySelectorAll('button')].find(b=>b.querySelector('b')?.textContent==='Membres').click();await wait();await wait();await f.click('Tester l’envoi au HUB');assert.ok(f.text().includes('SMTP 550'));assert.ok(f.text().includes('Mailbox unavailable'));assert.ok(f.text().includes('Aucune invitation membre n’est envoyée ni modifiée.'));assert.equal(diagnostic.length,1);assert.ok(!f.calls.some(c=>c.url.match(/members\/\d+\/invite$/)&&c.method==='POST'));assert.deepEqual(f.errors,[]);}finally{f.close();}});


test('both environments have a monthly agenda, event sharing and duty or replacement navigation',async()=>{
 for(const environment of ['MEMBERS','ALUMNI']){const f=await mount(environment);try{
  await f.click('Planning');assert.ok(f.text().includes('Planning du HUB'));
  assert.ok(f.text().includes('Portes ouvertes du membre'));assert.ok(f.text().includes('Conférence des anciens'));
  assert.equal(f.w.document.querySelectorAll('.weekday').length,7);
  assert.ok(f.w.document.querySelectorAll('.agendaDay').length>=28);
  const label=f.w.document.querySelector('.agendaHeading h2').textContent;
  f.w.document.querySelector('[aria-label="Mois suivant"]').click();await wait();await wait();
  assert.notEqual(f.w.document.querySelector('.agendaHeading h2').textContent,label);
  assert.ok(f.calls.filter(c=>c.url.includes('/agenda?month=')).length>=2);
  if(environment==='MEMBERS'){
   assert.ok(f.text().includes('Préparation de salle'));assert.ok(f.text().includes('Collègue Accueil'));
   assert.ok(f.text().indexOf('Mon prochain rôle d’accueil')<f.text().indexOf('Mes permanences et remplacements'));
  }else{assert.ok(f.text().includes('Une participation comme suppléant nécessite'));assert.ok(!f.calls.some(c=>c.url.endsWith('/planning/welcome')));}
  await f.click(' Partager un événement');const form=f.w.document.querySelector('form');
  assert.ok(form.elements.eventDate.required);assert.ok(form.elements.eventTime);assert.ok(form.elements.eventLocation);
  form.elements.title.value='Mon drink';form.elements.eventDate.value='2099-02-12';form.elements.message.value='Venez échanger';
  form.dispatchEvent(new f.w.Event('submit',{bubbles:true,cancelable:true}));await wait();await wait();
  assert.ok(f.text().includes('Votre événement est publié dans le Planning des membres et des anciens.'));
  assert.ok(f.calls.some(c=>c.url.endsWith('/me/requests')&&c.method==='POST'));
  await f.click('Planning');await f.click(' Mes permanences et remplacements');
  assert.ok(f.text().includes(environment==='MEMBERS'?"Mes fonctions d'accueil":'Mes disponibilités et sollicitations'));
  assert.deepEqual(f.errors,[]);
 }finally{f.close();}}
});

test('shared event notifications open their calendar month in both environments',async()=>{
 for(const environment of ['MEMBERS','ALUMNI']){const f=await mount(environment);try{
  const original=f.w.fetch;f.w.fetch=async(url,options)=>url.endsWith('/me/notifications')?{ok:true,json:async()=>({unread:1,items:[{id:10,title:'Nouvel événement',message:'Conférence',createdAt:new Date().toISOString(),link:'agenda:2099-02',read:true}]})}:original(url,options);
  f.w.document.querySelector('button[title="Notifications"]').click();await wait();await wait();
  const item=[...f.w.document.querySelectorAll('.memberList article')].find(x=>x.textContent.includes('Nouvel événement'));assert.ok(item);item.click();await wait();await wait();
  assert.ok(f.text().includes('Planning du HUB'));assert.ok(f.calls.some(c=>c.url.endsWith('/agenda?month=2099-02')));
  assert.deepEqual(f.errors,[]);
 }finally{f.close();}}
});


test('official home shows personal OFF figures below invited guests',async()=>{const f=await mount();try{
 const section=f.w.document.querySelector('section[aria-label="Mon activité OFF"]');assert.ok(section);
 assert.ok(f.text().indexOf('Invité du jeudi')<f.text().indexOf('Mon activité OFF'));
 const cards=[...section.querySelectorAll('.adminStats>div')];assert.equal(cards.length,4);
 assert.deepEqual(cards.map(x=>x.querySelector('span').textContent),['CA généré','CA donné','TAT effectués','Recommandations envoyées']);
 assert.deepEqual(cards.map(x=>x.querySelector('b').textContent.replace(/[\s€]/g,'')),['1250,50','375,00','4','7']);
 assert.ok(section.textContent.includes('Mandature en cours'));assert.deepEqual(f.errors,[]);
}finally{f.close();}});
