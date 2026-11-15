import React,{useEffect,useState} from 'react';
import {getSessionToken} from './session.js';
const API=import.meta.env.VITE_API_URL||'https://bni-hub-api-production.up.railway.app/api';
export const isEventImage=name=>/\.(png|jpe?g|webp)$/i.test(name||'');

export function useEventImagePreview(file){
 const[src,setSrc]=useState('');
 useEffect(()=>{if(!file||!isEventImage(file.name)){setSrc('');return}const url=URL.createObjectURL(file);setSrc(url);return()=>URL.revokeObjectURL(url)},[file]);
 return src;
}

export function EventIllustration({item}){
 const[src,setSrc]=useState(''),[failed,setFailed]=useState(false);
 useEffect(()=>{
  if(!item.attachmentId||!isEventImage(item.attachmentName))return;
  const controller=new AbortController();let url;
  setSrc('');setFailed(false);
  (async()=>{try{
   const response=await fetch(API+'/member-requests/'+item.attachmentId+'/attachment',{headers:{Authorization:'Bearer '+getSessionToken()},signal:controller.signal});
   if(!response.ok)throw new Error('Illustration indisponible');
   const blob=await response.blob();if(controller.signal.aborted)return;
   const extension=item.attachmentName.split('.').pop().toLowerCase();
   const type={png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',webp:'image/webp'}[extension];
   url=URL.createObjectURL(new Blob([blob],{type}));setSrc(url);
  }catch(error){if(error.name!=='AbortError')setFailed(true)}})();
  return()=>{controller.abort();if(url)URL.revokeObjectURL(url)};
 },[item.attachmentId,item.attachmentName]);
 if(!item.attachmentId||!isEventImage(item.attachmentName))return null;
 if(failed)return <p className="eventImageUnavailable">L’illustration ne peut pas être affichée. La pièce jointe reste disponible ci-dessous.</p>;
 if(!src)return <p className="eventImageLoading" role="status">Chargement de l’illustration…</p>;
 return <figure className="eventIllustration"><img src={src} alt={'Illustration de l’événement : '+(item.title||'Événement du groupe')} loading="lazy" onError={()=>setFailed(true)}/></figure>;
}
