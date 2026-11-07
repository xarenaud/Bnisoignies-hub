const test=require('node:test');const assert=require('node:assert/strict');const {JSDOM}=require('jsdom');const esbuild=require('esbuild');const path=require('node:path');
let bundle;
const wait=()=>new Promise(r=>setTimeout(r,60));
async function mount(environment='MEMBERS'){
 if(!bundle){const r=await esbuild.build({entryPoints:[path.join(__dirname,'../src/main.jsx')],bundle:true,write:false,format:'iife',loader:{'.css':'empty'},define:{'import.meta.env.VITE_API_URL':'"https://hub.test/api"','import.meta.env.PROD':'false'}});bundle=r.outputFiles[0].text;}
 const dom=new JSDOM('<div id="root"></div>',{url:'https://hub.test/',runScripts:'dangerously'}),w=dom.window;const errors=[];w.addEventListener('error',e=>errors.push(e.message));w.localStorage.setItem('bni_token','fixture');w.confirm=()=>true;
 let opted=false;const user=()=>({id:1,firstName:'Test',lastName:'Membre',email:'fixture@example.test',environment,alumniBridgeEnabled:opted,networkModuleEnabled:environment==='ALUMNI'||opted,networkAccessEnabled:environment==='ALUMNI'||opted,roles:[],isAdmin:false});
 w.fetch=async(url,options={})=>{const p=new URL(url).pathname.replace('/api','');let data=[];
  if(p==='/auth/me')data={member:user()};
  if(p==='/me/notifications')data={unread:0,items:[]};
  if(p==='/me/home')data={nextMeeting:null,memberStats:null,groupStats:null};
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
 return {w,errors,text,click,close:()=>w.close()};
}
test('official UI only exposes business actions after personal consent',async()=>{const f=await mount();try{await f.click('Participer');assert.ok(f.text().includes('Envoyer une infomerciale'));assert.ok(![...f.w.document.querySelectorAll('button')].some(b=>b.textContent==='MPB'));await f.click('Profil');await f.click('J’active personnellement ma liaison');await f.click('Participer');assert.ok([...f.w.document.querySelectorAll('button')].some(b=>b.textContent==='MPB'));await f.click('Recommandations');assert.ok(f.text().includes('Ancien autorisé'));await f.click('Profil');await f.click('Désactiver ma liaison');await f.click('Participer');assert.ok(![...f.w.document.querySelectorAll('button')].some(b=>b.textContent==='MPB'));assert.deepEqual(f.errors,[]);}finally{f.close();}});
test('alumni UI has exchanges and targeted substitutions, no official planning or resources',async()=>{const f=await mount('ALUMNI');try{assert.ok(f.text().includes('HUB Anciens'));const nav=[...f.w.document.querySelectorAll('nav button')].map(b=>b.textContent);assert.deepEqual(nav,['Accueil','Échanges','Suppléances','Profil']);await f.click('Échanges');assert.ok(f.text().includes('Donner une recommandation'));await f.click('Suppléances');assert.ok(f.text().includes('Proposer ma disponibilité'));await f.click('Profil');assert.ok(f.text().includes('Votre espace Anciens'));assert.deepEqual(f.errors,[]);}finally{f.close();}});
test('inactive former member can request access without exposing the group',async()=>{const f=await mount('INACTIVE');try{assert.ok(f.text().includes('Demander mon passage chez les anciens'));assert.ok(!f.w.document.querySelector('nav'));assert.ok(!f.text().includes('Prochaine réunion'));assert.deepEqual(f.errors,[]);}finally{f.close();}});
