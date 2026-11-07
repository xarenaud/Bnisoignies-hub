// Check the deployed release on launch and when a suspended app resumes.
export function installUpdates({version, win=window, doc=document, request=fetch}) {
  let checking=false;
  const dirty=()=>!!doc.querySelector('form[data-hub-dirty="true"]');
  function markDirty(event){event.target.closest?.('form')?.setAttribute('data-hub-dirty','true');}
  doc.addEventListener('input',markDirty,true);
  doc.addEventListener('change',markDirty,true);
  doc.addEventListener('reset',event=>event.target.removeAttribute?.('data-hub-dirty'),true);
  function showUpdate(reload){
    if(doc.getElementById('hub-update-notice'))return;
    const notice=doc.createElement('aside');notice.id='hub-update-notice';notice.setAttribute('role','status');
    notice.style.cssText='position:fixed;bottom:88px;left:16px;right:16px;z-index:1000;padding:16px;background:white;color:#20252b;border:1px solid #cf2030;border-radius:12px;box-shadow:0 4px 24px #0002';
    const message=doc.createElement('p');message.textContent='Une nouvelle version du Hub est disponible. Terminez votre saisie avant de mettre à jour.';
    const button=doc.createElement('button');button.className='primary';button.textContent='Mettre à jour';button.addEventListener('click',reload);
    notice.append(message,button);doc.body.append(notice);
  }
  async function check(){
    if(checking||doc.visibilityState==='hidden')return;
    checking=true;const controller=new AbortController();const timeout=win.setTimeout(()=>controller.abort(),8000);
    try{
      const url=new URL('./version.json',win.location.href);url.searchParams.set('check',String(Date.now()));
      const response=await request(url.href,{cache:'no-store',signal:controller.signal});
      if(!response.ok)return;
      const data=await response.json();
      if(typeof data.version!=='string'||!data.version||data.version===version)return;
      const attempt=version+':'+data.version;
      const reload=()=>{
        try{win.sessionStorage.setItem('hub_update_attempt',attempt);}catch{}
        const target=new URL(win.location.href);target.searchParams.set('_hub_update',data.version);
        win.location.replace(target.href);
      };
      let attempted=false;try{attempted=win.sessionStorage.getItem('hub_update_attempt')===attempt;}catch{}
      if(dirty()||attempted)showUpdate(reload);else reload();
    }catch{
      // Offline or temporarily unavailable: keep the existing app usable.
    }finally{win.clearTimeout(timeout);checking=false;}
  }
  win.addEventListener('pageshow',check);
  win.addEventListener('focus',check);
  doc.addEventListener('visibilitychange',()=>{if(doc.visibilityState==='visible')check();});
  return check();
}
