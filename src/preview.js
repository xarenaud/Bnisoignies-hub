// Isolated, in-memory walkthrough. Never grants server rights or sends a test write to production.
let session=null;
const day=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Brussels'}).format(new Date());
export function startPreview(admin){
 if(!admin?.isSystemAdmin)throw new Error('Aperçu réservé à l’administrateur système.');
 session={actor:'ALUMNI',bridge:false,referrals:[],business:[],otos:[],offers:[],requests:[],needs:[],notifications:[],seq:1};
}
export function stopPreview(){session=null;}
export function selectPreviewActor(actor){if(session)session.actor=actor;}
export function previewUser(){
 if(!session)return null;
 const alumni=session.actor!=='MEMBERS',second=session.actor==='ALUMNI2';
 return {id:second?-3:alumni?-2:-1,isPreview:true,firstName:second?'Autre ancien':alumni?'Ancien':'Membre',lastName:'Test',company:'Entreprise de démonstration',email:second?'ancien2@example.test':alumni?'ancien@example.test':'membre@example.test',roles:[],isAdmin:false,isSystemAdmin:false,environment:alumni?'ALUMNI':'MEMBERS',networkType:alumni?'OFF':'OFFICIAL_BNI',alumniBridgeEnabled:!alumni&&session.bridge,networkModuleEnabled:alumni||session.bridge,networkAccessEnabled:alumni||session.bridge,networkBridgeEnabled:!alumni&&session.bridge};
}
const name=id=>Number(id)===-3?'Autre ancien Test':Number(id)===-2?'Ancien Test':'Membre Test';
const result=(body,status=200)=>Promise.resolve({ok:status<400,status,json:async()=>JSON.parse(JSON.stringify(body))});
export function hubFetch(url,options={}){
 if(!session)return globalThis.fetch(url,options);
 const s=session,p=new URL(url,location.origin).pathname.replace(/^\/api/,'');
 // Authentication stays bound to the real administrator, including focus refreshes.
 if(p==='/auth/me'&&(!options.method||options.method==='GET'))return globalThis.fetch(url,options);
 const method=options.method||'GET',u=previewUser(),id=u.id,alumni=u.environment==='ALUMNI',data=typeof options.body==='string'?JSON.parse(options.body):{};
 const fail=message=>result({error:message},403);
 const notify=(to,title,message='Message simulé — aucun e-mail envoyé.')=>s.notifications.push({id:s.seq++,to,title,message,createdAt:new Date().toISOString(),read:false});
 const stats=()=>({mandate:'Parcours de test',referralsGiven:s.referrals.filter(x=>x.fromMemberId===id).length,referralsReceived:s.referrals.filter(x=>x.toMemberId===id).length,oneToOnes:s.otos.filter(x=>x.fromMemberId===id||x.partnerMemberId===id).length,businessGenerated:s.business.filter(x=>x.creditedMemberId===id).reduce((a,x)=>a+x.amount,0),businessReceived:s.business.filter(x=>x.fromMemberId===id).reduce((a,x)=>a+x.amount,0)});
 const pair=target=>{target=Number(target);return target!==id&&[-1,-2,-3].includes(target)&&((id!==-1&&target!==-1)||s.bridge);};
 if(p==='/me/alumni-bridge'&&method==='PUT'){
  if(alumni)return fail('Ce choix appartient au membre actif.');
  s.bridge=!!data.enabled;return result({member:previewUser(),bridgeEnabled:s.bridge});
 }
 if(p==='/alumni-space/me')return result({environment:u.environment,bridgeEnabled:s.bridge,requestedAt:null,stats:alumni?stats():null});
 if(p==='/me/profile'){
  if(method!=='GET')return fail('Le profil de test ne modifie aucun compte.');
  return result({...u,subscription:{label:'Compte fictif de démonstration'}});
 }
 if(p==='/me/past-stats')return result({mandates:[],stats:null});
 if(p==='/off-membership/me')return result({enabled:false});
 if(p==='/me/home')return result({memberStats:null,groupStats:null,nextMeeting:null});
 if(p.startsWith('/me/notifications')){
  const items=s.notifications.filter(x=>x.to===id);
  if(method==='POST')items.forEach(x=>{if(p.endsWith('read-all')||p.includes('/'+x.id+'/'))x.read=true;});
  return result({unread:items.filter(x=>!x.read).length,items});
 }
 if(p==='/network/config')return result({features:{REFERRALS:true,BUSINESS:true,ONE_TO_ONE:true},fullNetworkEnabled:alumni,networkBridgeEnabled:!alumni&&s.bridge,isSystemAdmin:false});
 if(p==='/network/members')return result([-1,-2,-3].filter(target=>pair(target)).map(target=>({id:target,name:name(target),networkType:target===-1?'OFFICIAL_BNI':'OFF',company:'Entreprise de démonstration'})));
 if(p==='/network/stats')return result(stats());
 if(p.startsWith('/network/')){
  if(!alumni&&!s.bridge)return fail('Activez la liaison personnelle dans Profil.');
  const collections={'/network/referrals':s.referrals,'/network/business':s.business,'/network/one-to-ones':s.otos};
  if(collections[p]){
   if(method==='GET')return result(collections[p].filter(x=>[x.fromMemberId,x.toMemberId,x.creditedMemberId,x.partnerMemberId].includes(id)));
   if(method!=='POST')return fail('Action non disponible dans ce parcours.');
   const target=Number(data.toMemberId||data.creditedMemberId||data.partnerMemberId);
   if(!pair(target))return fail('Le membre actif doit activer sa liaison personnelle.');
   const base={...data,id:s.seq++,createdAt:new Date().toISOString(),fromMemberId:id,fromMember:name(id)};
   if(p.endsWith('/referrals'))Object.assign(base,{toMemberId:target,toMember:name(target),status:'PENDING'});
   if(p.endsWith('/business'))Object.assign(base,{creditedMemberId:target,creditedMember:name(target),amount:Number(data.amount),businessDate:data.businessDate||day()});
   if(p.endsWith('/one-to-ones'))Object.assign(base,{partnerMemberId:target,memberA:name(id),memberB:name(target),meetingDate:data.meetingDate||day()});
   collections[p].unshift(base);notify(target,p.endsWith('/referrals')?'Nouvelle recommandation de test':p.endsWith('/business')?'Nouveau MPB de test':'Nouveau TAT de test');return result(base,201);
  }
  if(p.startsWith('/network/referrals/')&&method==='PATCH'){
   const r=s.referrals.find(x=>x.id===Number(p.split('/').pop()));
   if(!r||r.toMemberId!==id)return fail('Seul le destinataire peut suivre cette recommandation.');
   if(!['PENDING','NO_FOLLOW_UP','WON','LOST'].includes(data.status))return fail('Statut invalide.');
   if(data.status==='WON'&&r.status!=='WON'){
    const amount=Number(data.amount);if(!(amount>0))return fail('Montant positif requis.');
    r.businessAmount=amount;s.business.unshift({id:s.seq++,fromMemberId:id,fromMember:name(id),creditedMemberId:r.fromMemberId,creditedMember:r.fromMember,amount,businessDate:day(),notes:'Recommandation gagnée (test)'});notify(r.fromMemberId,'MPB automatique de test');
   }
   r.status=data.status;return result(r);
  }
 }
 if(p==='/alumni-space/availability'){
  if(method==='GET')return result(alumni?s.offers.filter(x=>x.memberId===id):s.bridge?s.offers:[]);
  if(!alumni)return fail('Seuls les anciens proposent une disponibilité.');
  if(!data.date||data.date<day())return fail('Choisissez une date à venir.');
  if(s.offers.some(x=>x.date===data.date&&x.memberId===id))return fail('Cette disponibilité existe déjà.');
  const offer={...data,id:s.seq++,memberId:id,member:name(id),company:'Entreprise de démonstration'};s.offers.push(offer);return result(offer,201);
 }
 if(p.startsWith('/alumni-space/availability/')&&method==='DELETE'){
  if(!alumni)return fail('Cette disponibilité appartient à l’ancien.');
  s.offers=s.offers.filter(x=>x.id!==Number(p.split('/').pop())||x.memberId!==id);return result({status:'ok'});
 }
 if(p==='/alumni-space/substitutions'){
  if(method==='GET')return result(alumni?s.requests.filter(x=>x.alumniId===id):s.bridge?s.requests:[]);
  if(alumni||!s.bridge)return fail('Seul le membre actif ayant activé sa liaison peut solliciter un ancien.');
  const o=s.offers.find(x=>x.id===Number(data.availabilityId));if(!o)return fail('Disponibilité introuvable.');
  if(s.requests.some(x=>x.date===o.date&&['REQUESTED','ACCEPTED'].includes(x.status)))return fail('Une demande existe déjà pour cette date.');
  const r={id:s.seq++,date:o.date,official:'Membre Test',alumniId:o.memberId,alumni:o.member,status:'REQUESTED',startTime:'07:00',location:'Lieu fictif de réunion'};s.requests.push(r);notify(o.memberId,'Demande de suppléance de test');return result(r,201);
 }
 if(p.startsWith('/alumni-space/substitutions/')&&method==='PATCH'){
  const r=s.requests.find(x=>x.id===Number(p.split('/').pop()));
  if(!r||!(alumni?r.alumniId===id&&['ACCEPTED','DECLINED'].includes(data.status)&&r.status==='REQUESTED':data.status==='CANCELLED'&&s.bridge))return fail('Cette action appartient à l’autre participant.');
  r.status=data.status;
  if(data.status==='ACCEPTED'){r.acceptedAt=new Date().toISOString();notify(-1,'Suppléance confirmée',r.alumni+' a accepté de remplacer '+r.official+' le '+r.date+'.');}
  else notify(alumni?-1:r.alumniId,'Réponse à la suppléance de test',name(id)+(data.status==='DECLINED'?' a refusé la demande de suppléance du ':' a annulé la demande de suppléance du ')+r.date+'.');
  return result(r);
 }
 // Open replacement call: publication and claim are synchronous in the isolated session.
 if(p==='/alumni-space/replacement-needs'){
  if(method==='GET')return result(s.needs);
  if(method!=='POST'||alumni||!s.bridge)return fail('Activez votre liaison personnelle pour publier un besoin.');
  if(!data.date||data.date<day())return fail('Choisissez une date à venir.');
  if(s.needs.some(x=>x.date===data.date&&['OPEN','ACCEPTED'].includes(x.status)))return fail('Un besoin existe déjà pour cette date.');
  const need={id:s.seq++,date:data.date,note:String(data.note||'').slice(0,500),officialId:id,official:name(id),status:'OPEN',alumniId:null,alumni:null,startTime:'07:00',location:'Lieu fictif de réunion'};
  s.needs.push(need);
  for(const target of [-2,-3])notify(target,'Suppléance recherchée',name(id)+' recherche un suppléant le '+need.date+'. Le premier ancien qui accepte s’engage à assurer son remplacement.');
  return result(need,201);
 }
 if(p.startsWith('/alumni-space/replacement-needs/')&&method==='POST'){
  if(!alumni)return fail('Seul un ancien peut accepter cette suppléance.');
  const need=s.needs.find(x=>x.id===Number(p.split('/').pop()));
  if(!need)return result({error:'Besoin introuvable.'},404);
  if(need.status!=='OPEN')return result({error:'Cette suppléance a déjà été prise en charge par '+need.alumni+'.'},409);
  // Check before assigning; no await between check and assignment, first acceptance wins.
  need.status='ACCEPTED';need.alumniId=id;need.alumni=name(id);need.acceptedAt=new Date().toISOString();
  notify(need.officialId,'Suppléance confirmée',name(id)+' a accepté de remplacer '+need.official+' le '+need.date+'.');
  for(const target of [-2,-3])notify(target,target===id?'Votre engagement est confirmé':'Suppléance pourvue',name(id)+' a accepté de remplacer '+need.official+' le '+need.date+'.');
  return result(need);
 }
 // Fail closed: unknown writes never leave the demo, even profile/password/group forms.
 if(method!=='GET')return fail('Cette action n’est pas simulée. Quittez le test pour agir sur votre compte réel.');
 return result([]);
}
