import React,{useEffect,useState} from 'react';
import {getSessionToken} from './session.js';
const API=import.meta.env.VITE_API_URL||'https://bni-hub-api-production.up.railway.app/api';
export function MeetingDetails({meetingId}){
 const[data,setData]=useState(null),[error,setError]=useState('');
 useEffect(()=>{const c=new AbortController();setData(null);setError('');fetch(API+'/agenda/meetings/'+meetingId,{signal:c.signal,headers:{Authorization:'Bearer '+getSessionToken()}}).then(async r=>{const x=await r.json();if(!r.ok)throw new Error(x.error||'Détails indisponibles.');return x}).then(setData).catch(e=>{if(e.name!=='AbortError')setError(e.message)});return()=>c.abort()},[meetingId]);
 if(error)return <p className="errorBox" role="alert">{error}</p>;
 if(!data)return <p role="status">Chargement des détails de la réunion…</p>;
 return <div className="meetingDetails" aria-label="Détails de la réunion"><section><h3>Qui fait quoi ?</h3>{data.assignments.length?data.assignments.map(a=><p key={a.id}><b>{a.duty}</b> : {a.member}{a.status==='TO_REASSIGN'?' · remplacement recherché':''}</p>):<p>Les permanences ne sont pas encore publiées.</p>}</section><section><h3>Invités et suppléants</h3>{data.guests.length?data.guests.map(g=><p key={g.id}><b>{g.name}</b>{g.company?' · '+g.company:''}<small>{g.replaces?'Suppléant de '+g.replaces:'Invité par '+g.invitedBy}</small></p>):<p>Aucun invité ou suppléant confirmé.</p>}</section></div>;
}
