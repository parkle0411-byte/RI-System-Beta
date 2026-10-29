const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(path.join(__dirname,'../src/alpha/draftAutosave.js'),'utf8').replace(/^import .*$/gm,'').replace('export function','function');
const pause=()=>new Promise(r=>setTimeout(r,15));
async function main(){
 let guard,cleanup;const context={ref:v=>({value:v}),nextTick:()=>Promise.resolve(),onBeforeUnmount:f=>cleanup=f,onBeforeRouteLeave:f=>guard=f,
  window:{addEventListener(){},removeEventListener(){}},setTimeout,clearTimeout};vm.createContext(context);vm.runInContext(source,context);
 let input={currency:'USD',name:''},id={},writes=[],active=0,max=0,hold=null,fail=false,applied=0;
 const enabled={value:false};const api=context.useDraftAutosave({enabled,snapshot:()=>({...input}),identity:()=>({...id}),
  save:async(data,identity)=>{active++;max=Math.max(max,active);writes.push({data,identity});try{if(hold)await hold;if(fail)throw Error('Network unavailable');return {uid:'saved',version:writes.length}}finally{active--}},
  applied:result=>{applied++;id={caseUid:result.uid,rowVersion:result.version}}});
 const touch=()=>api.touch({type:'input'});api.reset();input.currency='TWD';await api.blur();enabled.value=true;await api.blur();await pause();assert.equal(writes.length,0,'prefills must never create a draft');
 touch();input.name='first';await api.blur();await pause();assert.equal(writes.length,1);assert.equal(input.name,'first');assert.equal(id.caseUid,'saved');
 touch();input.name='typing';await pause();assert.equal(writes.length,1,'typing alone must not save');await api.blur();await pause();assert.equal(writes.length,2);
 let release;hold=new Promise(r=>release=r);touch();input.name='in flight';await api.blur();await pause();touch();input.name='latest';await api.blur();await pause();hold=null;release();await pause();await pause();
 assert.equal(max,1,'writes must be serial');assert.equal(writes.at(-1).data.name,'latest');assert.equal(writes.at(-1).identity.rowVersion,3,'queued save must use the acknowledged version');
 fail=true;touch();input.name='keep after failure';await api.blur();await pause();assert(api.error.value.includes('Network unavailable'));assert.equal(input.name,'keep after failure');fail=false;assert.equal(await api.flush(true),true);assert.equal(api.error.value,'');
 const before=applied;hold=new Promise(r=>release=r);touch();input.name='old editor';await api.blur();await pause();input={name:'new editor'};api.reset();id={};enabled.value=false;hold=null;release();await pause();assert.equal(applied,before,'late responses must not replace a new editor');assert.equal(input.name,'new editor');
 enabled.value=true;api.reset();input.name='prefilled';const count=writes.length;assert.equal(await guard(),true);assert.equal(writes.length,count,'leaving with only prefills must not save');touch();input.name='leave safely';assert.equal(await guard(),true);assert.equal(writes.at(-1).data.name,'leave safely');cleanup();
 console.log('PASS autosave: prefills, blur timing, serial writes, version handoff, retries, editor replacement and route leave');
}
main().catch(e=>{console.error(e);process.exit(1)});
