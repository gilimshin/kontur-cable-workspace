// Run only when the owner authorizes migration and shared-password access.
// Secrets are passed on stdin, never printed or stored in tracked files.
import { randomBytes } from 'node:crypto';
import { mkdirSync, existsSync, readFileSync, writeFileSync, chmodSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const root=fileURLToPath(new URL('../',import.meta.url));
process.chdir(root);
mkdirSync('.local',{recursive:true,mode:0o700});
const credentialPath=resolve('.local/site-access.json');
const access=existsSync(credentialPath)?JSON.parse(readFileSync(credentialPath,'utf8')):{url:'https://kontur-cable-workspace.vercel.app',password:randomBytes(24).toString('base64url')};
if(!existsSync(credentialPath))writeFileSync(credentialPath,JSON.stringify(access,null,2)+'\n',{mode:0o600,flag:'wx'});
function run(cmd,args,input){
  const r=spawnSync(cmd,args,{cwd:root,input,encoding:'utf8',maxBuffer:5_000_000});
  if(r.status!==0)throw new Error(`${cmd} ${args[0]} failed (${r.status}). Inspect service status before retrying.`);
  return r.stdout;
}
if(!access.passwordConfigured){
  run('vercel',['env','add','WORKSPACE_PASSWORD','production','--sensitive','--yes'],access.password);
  access.passwordConfigured=true;
  writeFileSync(credentialPath,JSON.stringify(access,null,2)+'\n',{mode:0o600});
}
console.log('Production password configured; credential saved locally with owner-only permissions.');
run('vercel',['env','pull','.local/production.env','--environment=production','--yes']);
chmodSync('.local/production.env',0o600);
process.loadEnvFile('.local/production.env');
const exported=run('python3',['scripts/export_workspace.py']);
const migrated=run(process.execPath,['scripts/migrate_to_blob.mjs'],exported);
console.log(migrated.trim());
console.log('Local credential file: '+credentialPath);
