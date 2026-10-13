import { randomUUID, createHash, createHmac, timingSafeEqual } from 'node:crypto';

export function equalSecret(a,b) {
  return timingSafeEqual(createHash('sha256').update(String(a)).digest(),createHash('sha256').update(String(b)).digest());
}
export function sessionToken(secret, now=Date.now()) {
  const body=Buffer.from(JSON.stringify({expires:now+7*24*3600*1000,nonce:randomUUID()})).toString('base64url');
  return body+'.'+createHmac('sha256',secret).update(body).digest('base64url');
}
export function validSession(token, secret, now=Date.now()) {
  try {
    const [body,signature]=String(token).split('.');
    if(!signature || !equalSecret(signature,createHmac('sha256',secret).update(body).digest('base64url'))) return false;
    return JSON.parse(Buffer.from(body,'base64url').toString()).expires>now;
  } catch {return false;}
}
export class UserError extends Error {constructor(status,message){super(message);this.status=status;}}
function text(value,max=10000) {return typeof value==='string'&&value.length<=max;}
export function validate(p) {
  if(!p || !text(p.name,200)||!p.name.trim()) throw new UserError(400,'Укажите название объекта (до 200 символов)');
  for(const k of ['address','description','projectCode','customer','contractor','subcontractor','owner','status','labExpiry','source']) if(!text(p[k]??''))throw new UserError(400,'Некорректное поле: '+k);
  for(const key of ['cables','dates','materials','notes','catalog']) if(!Array.isArray(p[key])||p[key].length>2000)throw new UserError(400,'Некорректный список: '+key);
  for(const key of ['cables','dates','materials']) {
    const ids=new Set();
    for(const item of p[key]) {if(!item || !text(item.id,100)||!item.id||ids.has(item.id))throw new UserError(400,'Некорректные идентификаторы строк');ids.add(item.id);}
  }
  for(const c of p.cables) {
    for(const key of ['direction','brand','section'])if(!text(c[key]))throw new UserError(400,'Некорректная кабельная линия');
    for(const key of ['ground','hdd','pipe','entry'])if(typeof c[key]!=='number'||!Number.isFinite(c[key])||c[key]<0||c[key]>1000000)throw new UserError(400,'Длины должны быть от 0 до 1 000 000 м');
  }
  for(const d of p.dates) {
    if(!text(d.name)||!text(d.note??''))throw new UserError(400,'Некорректный этап');
    for(const key of ['start','end'])if(d[key]&&(!/^\d{4}-\d{2}-\d{2}$/.test(d[key])||!Number.isFinite(Date.parse(d[key]))||new Date(d[key]).toISOString().slice(0,10)!==d[key]))throw new UserError(400,'Некорректная дата');
    if(d.start&&d.end&&d.end<d.start)throw new UserError(400,'Окончание работ раньше начала');
  }
  for(const m of p.materials)for(const key of ['name','manufacturer','quantity','passport','status'])if(!text(m[key]??''))throw new UserError(400,'Некорректные данные материала');
  for(const n of p.notes)if(!n||!text(n.text,2000)||!text(n.actor,100)||!text(n.time,100))throw new UserError(400,'Некорректная заметка');
  for(const s of p.catalog)if(!s||!text(s.name,100)||typeof s.hidden!=='boolean')throw new UserError(400,'Некорректный каталог');
}
export function changeProject(state,input,actor,create) {
  const p=structuredClone(input);validate(p);
  let action='Создан объект';
  if(create) {p.id=randomUUID();p.revision=1;}
  else {
    const previous=state.projects.find(x=>x.id===p.id);
    if(!previous)throw new UserError(404,'Объект не найден');
    if(previous.revision!==p.revision)throw new UserError(409,'Объект изменён в другом окне. Скопируйте свои изменения и обновите страницу.');
    if(JSON.stringify(previous)===JSON.stringify(p))return {project:p,changed:false};
    p.revision++;
    const labels={cables:'кабельные линии',dates:'даты работ',materials:'материалы',notes:'заметки',owner:'ответственный',status:'статус'};
    action='Обновлено: '+[...new Set(Object.keys(p).filter(k=>!['id','revision'].includes(k)&&JSON.stringify(p[k])!==JSON.stringify(previous[k])).map(k=>labels[k]||'реквизиты'))].join(', ');
  }
  if(create)state.projects.push(p);else state.projects=state.projects.map(x=>x.id===p.id?p:x);
  state.events.push({id:randomUUID(),project:p.id,actor:String(actor||'Участник команды').slice(0,100),action,time:new Date().toISOString()});
  return {project:p,changed:true};
}
