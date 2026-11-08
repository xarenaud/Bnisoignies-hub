import React from 'react';
export function LinkedText({text=''}){
 const parts=[];const pattern=/\b(?:https?:\/\/|www\.)[^\s<>"']+/gi;let cursor=0;
 for(const match of String(text).matchAll(pattern)){
  let label=match[0].replace(/[.,!?;:]+$/,'');
  for(const [open,close] of [['(',')'],['[',']'],['{','}']])while(label.endsWith(close)&&label.split(close).length>label.split(open).length)label=label.slice(0,-1);
  let url;try{url=new URL(/^www\./i.test(label)?'https://'+label:label)}catch{continue}
  if(!['http:','https:'].includes(url.protocol)||!url.hostname)continue;
  parts.push(String(text).slice(cursor,match.index));
  parts.push(<a key={match.index} href={url.href} target="_blank" rel="noopener noreferrer" title="Ouvrir dans le navigateur (nouvel onglet)">{label}</a>);
  cursor=match.index+label.length;
 }
 parts.push(String(text).slice(cursor));return <>{parts}</>;
}
