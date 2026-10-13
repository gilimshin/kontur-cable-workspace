import test from 'node:test';
import assert from 'node:assert/strict';
import {sessionToken,validSession,validate,changeProject} from '../lib/workspace.js';
const project=()=>({name:'Test',cables:[{id:'1',direction:'A-B',brand:'Cable',section:'4x185',ground:1,hdd:0,pipe:0,entry:0}],dates:[],materials:[],notes:[],catalog:[]});
test('sessions are signed, expire and become invalid after password change',()=>{
 const secret='test-password-with-at-least-24-characters';const token=sessionToken(secret,1000);
 assert.equal(validSession(token,secret,1001),true);assert.equal(validSession(token+'x',secret,1001),false);
 assert.equal(validSession(token,'changed',1001),false);assert.equal(validSession(token,secret,1000+8*86400000),false);
});
test('save increments revision, records event and rejects stale overwrite',()=>{
 const state={projects:[],events:[]};const created=changeProject(state,project(),'Engineer',true).project;
 const stale=structuredClone(created);const changed=structuredClone(created);changed.name='Updated';
 const result=changeProject(state,changed,'Engineer',false);
 assert.equal(result.project.revision,2);assert.equal(state.events.length,2);
 assert.throws(()=>changeProject(state,stale,'Other',false),e=>e.status===409);
 assert.equal(state.projects[0].name,'Updated');
});
test('rejects negative lengths, duplicate IDs, impossible dates and reversed dates',()=>{
 const p=project();p.cables[0].ground=-1;assert.throws(()=>validate(p));p.cables[0].ground=1;
 p.cables.push({...p.cables[0]});assert.throws(()=>validate(p));p.cables.pop();
 p.dates=[{id:'1',name:'Work',note:'',start:'2026-02-31',end:''}];assert.throws(()=>validate(p));
 p.dates[0].start='2026-10-13';p.dates[0].end='2026-10-12';assert.throws(()=>validate(p));
});
