"""Organizer-only manual registrations, including accompanying participants."""
import json,re,secrets
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo
from flask import Response,redirect,request,session

def install(app,database,admin_required,same_origin,valid_name,unit_price,mail_wake):
    @app.route('/admin/inscriptions/nouvelle',methods=['GET','POST'])
    @admin_required
    def manual_registration():
        csrf=session.setdefault('manual_registration_csrf',secrets.token_hex(24))
        data=request.form if request.method=='POST' else {}
        firsts=request.form.getlist('guestFirstName') if request.method=='POST' else []
        lasts=request.form.getlist('guestLastName') if request.method=='POST' else []
        error=''
        try:count=int(data.get('count',1))
        except (ValueError,TypeError):count=0
        form_id=data.get('formId','') or secrets.token_hex(16)
        if request.method=='POST':
            if not same_origin() or not secrets.compare_digest(data.get('csrf','').encode(),csrf.encode()):
                return Response('La session du formulaire a expiré. Rechargez la page.',403)
            first=data.get('firstName','').strip();last=data.get('lastName','').strip()
            group=data.get('group','').strip();email=data.get('email','').strip().lower()
            phone=data.get('phone','').strip();vat=data.get('vatNumber','').strip().upper()
            notify=data.get('sendConfirmation')=='yes'
            guests=[dict(firstName=a.strip(),lastName=b.strip()) for a,b in zip(firsts,lasts)]
            if not re.fullmatch(r'[a-f0-9]{32}',form_id):
                error='Le formulaire est invalide. Rechargez la page.'
            elif not valid_name(first) or not valid_name(last):
                error='Indiquez le prénom et le nom du participant principal.'
            elif not 1<=count<=100 or len(firsts)!=count-1 or len(lasts)!=count-1 or not all(valid_name(g['firstName']) and valid_name(g['lastName']) for g in guests):
                error='Renseignez le prénom et le nom de chaque accompagnant.'
            elif len(group)>100:
                error='Le nom du groupe est trop long.'
            elif email and (len(email)>254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',email)):
                error='Vérifiez l’adresse email.'
            elif phone and (len(phone)>35 or not re.fullmatch(r'[+0-9() .-]{6,35}',phone) or sum(c.isdigit() for c in phone)<6):
                error='Vérifiez le numéro de téléphone.'
            elif vat and not re.fullmatch(r'[A-Za-z0-9 .-]{4,32}',vat):
                error='Vérifiez le numéro de TVA.'
            elif notify and not email:
                error='Une adresse email est nécessaire pour envoyer la confirmation.'
            if not error:
                created=datetime.now(ZoneInfo('Europe/Brussels')).isoformat()
                fingerprint='manual:'+form_id
                payload=dict(firstName=first,lastName=last,group=group,email=email,phone=phone,
                    count=count,guests=guests,invoiceRequested=bool(vat),vatNumber=vat,
                    unitPrice=unit_price,manualRegistration=True,manualCreatedAt=created,
                    paymentAccepted=False,paymentTerms='Inscription enregistrée manuellement par l’organisateur.')
                with database() as db:
                    db.execute('BEGIN IMMEDIATE')
                    existing=db.execute('SELECT reference FROM registrations WHERE fingerprint=?',(fingerprint,)).fetchone()
                    if existing:
                        return redirect('/admin/inscriptions?added='+existing['reference'],code=303)
                    reference='BNI-'+secrets.token_hex(5).upper()
                    db.execute('INSERT INTO registrations(reference,fingerprint,payload,count,total,created_at,is_test) VALUES(?,?,?,?,?,?,0)',
                        (reference,fingerprint,json.dumps(payload,ensure_ascii=False,sort_keys=True),count,count*unit_price,created))
                    if notify:
                        db.executemany('INSERT INTO email_deliveries(reference,kind) VALUES(?,?)',[(reference,'participant'),(reference,'organizer')])
                if notify:mail_wake.set()
                return redirect('/admin/inscriptions?added='+reference,code=303)
        def field(label,name,kind='text',required=False,value=None):
            val=data.get(name,'') if value is None else value
            return '<label>'+label+'<input type="'+kind+'" name="'+name+'" value="'+escape(str(val),quote=True)+'"'+(' required' if required else '')+' maxlength="'+('254' if name=='email' else '100')+'"></label>'
        body='<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ajouter une inscription · Inter BNI</title><link rel="stylesheet" href="/admin/inscriptions.css"><link rel="stylesheet" href="/admin/inscriptions/nouvelle.css"></head><body><main><p class="brand">BNI SOIGNIES · ESPACE ORGANISATEUR</p><h1>Ajouter une inscription</h1><p>L’ajout manuel reste disponible après la clôture des inscriptions en ligne.</p><nav><a href="/admin/inscriptions">Retour à la liste des inscrits</a></nav>'
        if error:body+='<p class="error" role="alert">'+escape(error)+'</p>'
        body+='<form method="post" action="/admin/inscriptions/nouvelle"><input type="hidden" name="csrf" value="'+csrf+'"><input type="hidden" name="formId" value="'+escape(form_id,quote=True)+'"><h2>Participant principal</h2><div class="row">'+field('Prénom','firstName',required=True)+field('Nom','lastName',required=True)+'</div>'+field('Groupe BNI / organisation (facultatif)','group')+'<div class="row">'+field('Email (facultatif)','email','email')+field('Téléphone (facultatif)','phone','tel')+'</div>'+field('N° de TVA pour une note de frais (facultatif)','vatNumber')+'<label>Nombre total de personnes, participant principal compris<input type="number" id="manual-count" name="count" min="1" max="100" value="'+str(max(1,min(count,100)))+'" required></label><div id="manual-guests">'
        for i in range(max(0,min(count,100)-1)):
            body+='<fieldset><legend>Accompagnant '+str(i+1)+'</legend><div class="row">'+field('Prénom','guestFirstName',required=True,value=firsts[i] if i<len(firsts) else '')+field('Nom','guestLastName',required=True,value=lasts[i] if i<len(lasts) else '')+'</div></fieldset>'
        body+='</div><p class="total">Montant de la réservation : <strong id="manual-total">'+str(max(1,count)*unit_price)+' €</strong> ('+str(unit_price)+' € par personne).</p><p>Le paiement sera indiqué comme non confirmé. Vous pourrez ensuite le valider depuis « Paiement / note de frais ».</p><label class="check"><input type="checkbox" name="sendConfirmation" value="yes"'+(' checked' if data.get('sendConfirmation')=='yes' else '')+'> Envoyer l’email de confirmation au participant principal et une copie à l’organisation</label><button type="submit" class="button">Ajouter l’inscription</button></form></main><script src="/admin/inscriptions/nouvelle.js"></script></body></html>'
        return Response(body,status=422 if error else 200,mimetype='text/html')

    @app.get('/admin/inscriptions/nouvelle.css')
    @admin_required
    def manual_registration_css():
        return Response('main{max-width:1000px}form{max-width:800px;background:#192332;padding:28px;border-top:3px solid #cf2030}.row{display:grid;grid-template-columns:1fr 1fr;gap:20px}label{display:block;margin:18px 0}input{display:block;width:100%;padding:12px;border:1px solid #7b8b9e;border-radius:4px;background:#fff;color:#17202b;font:inherit;margin-top:7px}.check{display:flex;gap:12px;align-items:flex-start}.check input{width:20px;flex-shrink:0;margin-top:5px}.button{border:0;font:inherit;cursor:pointer}.error{background:#5b2330;padding:16px;border-left:4px solid #ff879b}fieldset{margin:20px 0;border:1px solid #53647b;padding:14px}legend{padding:0 8px}button:focus-visible,input:focus-visible{outline:3px solid #ffadb9;outline-offset:3px}@media(max-width:650px){.row{grid-template-columns:1fr;gap:0}form{padding:20px}}',mimetype='text/css')

    @app.get('/admin/inscriptions/nouvelle.js')
    @admin_required
    def manual_registration_js():
        return Response("""const count=document.querySelector('#manual-count'),guests=document.querySelector('#manual-guests');
count.addEventListener('input',()=>{
const n=Number(count.value);if(!Number.isInteger(n)||n<1||n>100)return;
const previous=[...guests.querySelectorAll('fieldset')].map(f=>[...f.querySelectorAll('input')].map(i=>i.value));
guests.replaceChildren();
for(let i=0;i<n-1;i++){const f=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent='Accompagnant '+(i+1);f.append(legend);const row=document.createElement('div');row.className='row';
for(const [j,name] of ['guestFirstName','guestLastName'].entries()){const label=document.createElement('label');label.textContent=j?'Nom':'Prénom';const input=document.createElement('input');input.name=name;input.required=true;input.maxLength=100;input.value=previous[i]?.[j]||'';label.append(input);row.append(label);}f.append(row);guests.append(f);}
document.querySelector('#manual-total').textContent=(n*10)+' €';
});""",mimetype='application/javascript')
