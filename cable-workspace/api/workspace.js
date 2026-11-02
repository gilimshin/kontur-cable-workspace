import { get, put, BlobPreconditionFailedError } from '@vercel/blob';
import { randomUUID } from 'node:crypto';
import { equalSecret, sessionToken, validSession, changeProject, UserError } from '../lib/workspace.js';

const FILE='kontur/workspace.json';
function reply(res,status,data){res.statusCode=status;res.setHeader('Content-Type','application/json; charset=utf-8');res.setHeader('Cache-Control','private, no-store');res.end(JSON.stringify(data));}
function isBlobConflict(e){return e instanceof BlobPreconditionFailedError||e?.name==='BlobAlreadyExistsError';}
async function readWorkspace(){const stored=await get(FILE,{access:'private',useCache:false});return {stored,state:stored?await new Response(stored.stream).json():{projects:[],events:[]}};}
async function writeWorkspace(stored,state){const data=JSON.stringify(state);if(Buffer.byteLength(data)>8_000_000)throw new UserError(413,'Хранилище MVP достигло лимита 8 МБ. Нужна миграция базы.');await put(FILE,data,{access:'private',addRandomSuffix:false,contentType:'application/json',cacheControlMaxAge:60,...(stored?{ifMatch:stored.blob.etag}:{allowOverwrite:false})});}
export default async function handler(req,res) {
  const password=process.env.WORKSPACE_PASSWORD;
  if(!password || password.length<24)return reply(res,503,{error:'Доступ ещё не настроен'});
  const url=new URL(req.url,'https://'+req.headers.host);
  const route=String(req.query?.route||url.searchParams.get('route')||url.pathname.replace(/^\/api\//,''));
  try {
    const mutation=['POST','PUT','DELETE'].includes(req.method);
    if(mutation) {
      if(!String(req.headers['content-type']).startsWith('application/json'))throw new UserError(415,'Ожидается JSON');
      if(req.headers.origin && new URL(req.headers.origin).host!==req.headers.host)throw new UserError(403,'Недопустимый источник запроса');
    }
    let body=req.body;
    if(typeof body==='string') {if(Buffer.byteLength(body)>2_000_000)throw new UserError(413,'Слишком большой запрос');body=JSON.parse(body);}
    if(mutation&&Buffer.byteLength(JSON.stringify(body??{}))>2_000_000)throw new UserError(413,'Слишком большой запрос');
    if(route==='login'&&req.method==='POST') {
      if(!equalSecret(body?.password,password))return reply(res,401,{error:'Неверный пароль'});
      res.setHeader('Set-Cookie',`kontur_session=${sessionToken(password)}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=604800`);
      return reply(res,200,{ok:true});
    }
    if(route==='logout'&&req.method==='POST') {
      res.setHeader('Set-Cookie','kontur_session=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0');return reply(res,200,{ok:true});
    }
    const cookie=String(req.headers.cookie||'').split(';').map(s=>s.trim()).find(s=>s.startsWith('kontur_session='))?.slice('kontur_session='.length);
    if(!validSession(cookie,password))return reply(res,401,{error:'Войдите в рабочее пространство'});
    const {stored,state}=await readWorkspace();
    if(route==='projects'&&req.method==='GET')return reply(res,200,state.projects);
    if(route.startsWith('events/')&&req.method==='GET')return reply(res,200,state.events.filter(e=>e.project===route.slice(7)).slice(-100).reverse());
    if(route==='projects'&&req.method==='DELETE') {
      const id=body?.id;
      if(typeof id!=='string'||!id)throw new UserError(400,'Не указан объект для удаления');
      for(let attempt=0;attempt<4;attempt++){
        const current=attempt===0?{stored,state}:await readWorkspace();
        if(!current.state.projects.some(project=>project.id===id))throw new UserError(404,'Объект не найден');
        current.state.projects=current.state.projects.filter(project=>project.id!==id);
        current.state.events=current.state.events.filter(event=>event.project!==id);
        try{await writeWorkspace(current.stored,current.state);return reply(res,200,{ok:true,id});}
        catch(e){if(!isBlobConflict(e)||attempt===3)throw e;await new Promise(resolve=>setTimeout(resolve,50*(attempt+1)));}
      }
    }
    if(route==='projects'&&['POST','PUT'].includes(req.method)) {
      const creating=req.method==='POST';
      const input=body?.project;
      if(creating&&input&&(!input.id||typeof input.id!=='string'))input.id=randomUUID();
      for(let attempt=0;attempt<4;attempt++){
        const current=attempt===0?{stored,state}:await readWorkspace();
        const {project,changed}=changeProject(current.state,input,body?.actor,creating);
        if(!changed)return reply(res,200,project);
        try{await writeWorkspace(current.stored,current.state);return reply(res,200,project);}
        catch(e){if(!isBlobConflict(e)||attempt===3)throw e;await new Promise(resolve=>setTimeout(resolve,50*(attempt+1)));}
      }
    }
    return reply(res,404,{error:'Не найдено'});
  } catch(e) {
    if(isBlobConflict(e))return reply(res,409,{error:'Параллельное сохранение. Повторите сохранение; если объект изменён, обновите страницу.'});
    if(e instanceof UserError)return reply(res,e.status,{error:e.message});
    if(e instanceof SyntaxError)return reply(res,400,{error:'Некорректный JSON'});
    console.error('Workspace request failed',e.name);
    return reply(res,503,{error:'Хранилище временно недоступно. Изменения не сохранены; повторите попытку.'});
  }
}
