import { get, put } from '@vercel/blob';
import { validate } from '../lib/workspace.js';

let input='';
for await(const chunk of process.stdin)input+=chunk;
const state=JSON.parse(input);
if(!Array.isArray(state.projects)||!Array.isArray(state.events))throw new Error('Invalid workspace');
state.projects.forEach(validate);
if(Buffer.byteLength(input)>8_000_000)throw new Error('Workspace exceeds MVP size limit');
const existing=await get('kontur/workspace.json',{access:'private',useCache:false});
if(existing)throw new Error('Cloud workspace already exists. Migration refuses to overwrite it.');
await put('kontur/workspace.json',JSON.stringify(state),{access:'private',addRandomSuffix:false,allowOverwrite:false,contentType:'application/json',cacheControlMaxAge:60});
console.log(`Migrated ${state.projects.length} project(s) and ${state.events.length} event(s).`);
