const UNIT_PRICE = 10;
const form=document.querySelector('#form'),count=document.querySelector('#count'),guests=document.querySelector('#guests'),status=document.querySelector('#status');
const invoiceRequested=document.querySelector('#invoiceRequested'),vatNumber=document.querySelector('#vatNumber');
invoiceRequested.addEventListener('change',()=>{document.querySelector('#billingFields').hidden=!invoiceRequested.checked;vatNumber.required=invoiceRequested.checked;if(!invoiceRequested.checked)vatNumber.value='';});
function update(){
  const n=Number(count.value);
  if(!Number.isInteger(n)||n<1||n>100)return;
  const previous=[...guests.querySelectorAll('.row')].map(row=>[...row.querySelectorAll('input')].map(x=>x.value));
  guests.replaceChildren();
  for(let i=1;i<n;i++){
    const row=document.createElement('div');row.className='row';
    for(const [j,title] of ['Prénom','Nom'].entries()){
      const label=document.createElement('label');label.textContent=`${title} · accompagnant ${i}`;
      const input=document.createElement('input');input.required=true;input.maxLength=100;input.name=`guest_${i}_${j}`;input.value=previous[i-1]?.[j]||'';
      label.append(input);row.append(label);
    }
    guests.append(row);
  }
  document.querySelector('#total').textContent=`${n*UNIT_PRICE} €`;
  document.querySelector('#calculation').textContent=`${n} × ${UNIT_PRICE} €`;
  document.querySelector('#paymentTerms').textContent=`Je confirme mon inscription pour ${n} personne(s) et m’engage à payer ${n*UNIT_PRICE} €, même en cas d’absence de tout ou partie des participants.`;
  document.querySelector('#submit').textContent=`Confirmer et m’engager à payer ${n*UNIT_PRICE} €`;
  document.querySelector('#paymentAccepted').checked=false;
}
count.addEventListener('input',update);
form.addEventListener('submit',async e=>{
  e.preventDefault();if(!form.reportValidity())return;
  const button=document.querySelector('#submit');button.disabled=true;status.className='';status.textContent='Enregistrement en cours…';
  const data=new FormData(form);
  const payload={
    firstName:data.get('firstName').trim(),lastName:data.get('lastName').trim(),group:data.get('group').trim(),
    email:data.get('email').trim(),phone:data.get('phone').trim(),invoiceRequested:invoiceRequested.checked,
    vatNumber:invoiceRequested.checked?vatNumber.value.trim():'',paymentAccepted:document.querySelector('#paymentAccepted').checked,
    count:Number(count.value),website:data.get('website'),
    guests:[...guests.querySelectorAll('.row')].map(row=>{const inputs=row.querySelectorAll('input');return{firstName:inputs[0].value.trim(),lastName:inputs[1].value.trim()};})
  };
  try{
    const response=await fetch('register.php',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||'Enregistrement impossible.');
    status.className='success';
    status.textContent=`Inscription enregistrée · Référence ${result.reference}. ${result.count} place(s), ${result.total} € à virer sur BE16 1431 1380 7474, bénéficiaire BNI SOIGNIES. Communication : ${payload.lastName} ${payload.firstName} ${payload.group}. Un email de confirmation va vous être envoyé à ${payload.email}. Le paiement reste à effectuer ; le montant est dû même en cas d’absence.`;
    form.querySelectorAll('input,select,button').forEach(x=>x.disabled=true);
    status.scrollIntoView({block:'center',behavior:'smooth'});
  }catch(error){status.textContent=`L’inscription n’a pas pu être confirmée : ${error.message} Réessayez ou contactez event@bim-soignies.be.`;button.disabled=false;}
});
