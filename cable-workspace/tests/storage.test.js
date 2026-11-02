import test from 'node:test';
import assert from 'node:assert/strict';
import { BlobNotFoundError, BlobPreconditionFailedError } from '@vercel/blob';
import { workspaceStorage } from '../lib/storage.js';
import { changeProject } from '../lib/workspace.js';
const project=()=>({name:'New object',cables:[],dates:[],materials:[],notes:[],catalog:[]});
function fixture(initial={projects:[],events:[]}) {
  let state=initial, version=1;
  const calls=[];
  const client={
    async head(){calls.push('head');if(!state)throw new BlobNotFoundError();return {etag:`"storage-${version}"`};},
    async get(){calls.push('get');return state?{blob:{etag:'content-etag'},stream:new Response(JSON.stringify(state)).body}:null;},
    async put(path,data,options){
      calls.push('put');
      if(state&&(options.allowOverwrite!==true||options.ifMatch!==`"storage-${version}"`))throw new BlobPreconditionFailedError();
      if(!state)assert.equal(options.allowOverwrite,false);
      state=JSON.parse(data);version++;
    }
  };
  return {client,calls,read:()=>state,storage:workspaceStorage(client)};
}
test('create in existing storage uses metadata ETag, preserving existing objects and history',async()=>{
  const f=fixture();changeProject(f.read(),project(),'First',true);
  const {stored,state}=await f.storage.readWorkspace();
  changeProject(state,project(),'Second',true);
  await f.storage.writeWorkspace(stored,state);
  assert.deepEqual(f.calls,['head','get','put']);
  assert.equal(f.read().projects.length,2);assert.equal(f.read().events.length,2);
});
test('first save creates a missing workspace without allowing overwrite',async()=>{
  const f=fixture(null);const {stored,state}=await f.storage.readWorkspace();
  changeProject(state,project(),'First',true);await f.storage.writeWorkspace(stored,state);
  assert.equal(f.read().projects.length,1);
});
test('concurrent write between metadata and content reads cannot be overwritten',async()=>{
  const f=fixture();const originalGet=f.client.get;
  f.client.get=async()=>{
    await f.client.put('',JSON.stringify({projects:[{id:'other'}],events:[]}),{allowOverwrite:true,ifMatch:'"storage-1"'});
    return originalGet();
  };
  const {stored,state}=await f.storage.readWorkspace();
  changeProject(state,project(),'Second',true);
  await assert.rejects(f.storage.writeWorkspace(stored,state),BlobPreconditionFailedError);
  assert.deepEqual(f.read().projects,[{id:'other'}]);
});
test('missing metadata ETag never permits an unconditional overwrite',async()=>{
  const f=fixture();await assert.rejects(f.storage.writeWorkspace({},f.read()),/Missing workspace ETag/);
  assert.deepEqual(f.calls,[]);
});
test('workspace appearing between reads causes a conflict',async()=>{
  const f=fixture();f.client.head=async()=>{throw new BlobNotFoundError();};
  await assert.rejects(f.storage.readWorkspace(),BlobPreconditionFailedError);
});
