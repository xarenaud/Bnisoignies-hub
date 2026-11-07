import test from 'node:test';
import assert from 'node:assert/strict';
import {installUpdates} from '../src/updates.js';
function fixture({remote='next',dirty=false,offline=false,attempted=false}={}){
  const state={navigations:[],nodes:[],listeners:{},url:null};
  const win={location:{href:'https://hub.bim-soignies.be/?network=business',replace:url=>state.navigations.push(url)},sessionStorage:{getItem:()=>attempted?'old:next':null,setItem:()=>{}},setTimeout,clearTimeout,addEventListener:(name,fn)=>state.listeners[name]=fn};
  const doc={visibilityState:'visible',querySelector:()=>dirty?{}:null,getElementById:()=>null,addEventListener:(name,fn)=>state.listeners[name]=fn,createElement:()=>({style:{},setAttribute(){},append(){},addEventListener(){}}),body:{append:node=>state.nodes.push(node)}};
  const request=async(url,options)=>{state.url=url;assert.equal(options.cache,'no-store');if(offline)throw Error('offline');return {ok:true,json:async()=>({version:remote})};};
  return {state,win,doc,request,version:'old'};
}
test('new release reloads once and preserves deep links',async()=>{const f=fixture();await installUpdates(f);assert.equal(f.state.navigations.length,1);const url=new URL(f.state.navigations[0]);assert.equal(url.searchParams.get('network'),'business');assert.equal(url.searchParams.get('_hub_update'),'next');});
test('current release stays on the page',async()=>{const f=fixture({remote:'old'});await installUpdates(f);assert.equal(f.state.navigations.length,0);assert.equal(f.state.nodes.length,0);});
test('unsaved form shows a button instead of losing input',async()=>{const f=fixture({dirty:true});await installUpdates(f);assert.equal(f.state.navigations.length,0);assert.equal(f.state.nodes.length,1);});
test('offline resumes without breaking the app',async()=>{const f=fixture({offline:true});await installUpdates(f);assert.equal(f.state.navigations.length,0);assert.equal(typeof f.state.listeners.focus,'function');assert.equal(typeof f.state.listeners.pageshow,'function');});
test('stale HTML cannot cause a reload loop',async()=>{const f=fixture({attempted:true});await installUpdates(f);assert.equal(f.state.navigations.length,0);assert.equal(f.state.nodes.length,1);});
