const test=require('node:test');const assert=require('node:assert/strict');const {JSDOM}=require('jsdom');const esbuild=require('esbuild');const path=require('node:path');
test('event illustration fetches with HUB authentication and revokes private image on removal',async()=>{
 const result=await esbuild.build({stdin:{contents:`import React from 'react';import{createRoot}from'react-dom/client';import{EventIllustration}from'./src/event-image.jsx';const root=createRoot(document.getElementById('root'));window.renderImage=item=>root.render(React.createElement(EventIllustration,{item}));window.unmountImage=()=>root.unmount();`,resolveDir:path.join(__dirname,'..'),loader:'jsx'},bundle:true,write:false,format:'iife',define:{'import.meta.env.VITE_API_URL':'"https://hub.test/api"'}});
 const dom=new JSDOM('<div id="root"></div>',{url:'https://hub.test',runScripts:'dangerously'});const w=dom.window,calls=[],revoked=[];
 w.localStorage.setItem('bni_token','private-fixture-token');w.URL.createObjectURL=()=> 'blob:private-image';w.URL.revokeObjectURL=url=>revoked.push(url);
 w.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,blob:async()=>new w.Blob(['fixture'],{type:'image/jpeg'})}};
 w.eval(result.outputFiles[0].text);w.renderImage({attachmentId:41,attachmentName:'affiche.jpg',title:'Portes ouvertes'});
 for(let i=0;i<30&&!w.document.querySelector('img');i++)await new Promise(r=>setTimeout(r,10));
 assert.equal(calls.length,1);assert.equal(calls[0].url,'https://hub.test/api/member-requests/41/attachment');assert.equal(calls[0].options.headers.Authorization,'Bearer private-fixture-token');
 const image=w.document.querySelector('img');assert.ok(image);assert.equal(image.src,'blob:private-image');assert.match(image.alt,/Portes ouvertes/);
 w.renderImage({attachmentId:42,attachmentName:'document.pdf',title:'Autre document'});await new Promise(r=>setTimeout(r,40));
 assert.equal(w.document.querySelector('img'),null);assert.equal(calls.length,1);assert.deepEqual(revoked,['blob:private-image']);
 w.unmountImage();dom.window.close();
});
