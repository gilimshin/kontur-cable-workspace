import { get, head, put, BlobNotFoundError, BlobPreconditionFailedError } from '@vercel/blob';
import { UserError } from './workspace.js';

const FILE='kontur/workspace.json';
export function workspaceStorage(client={get,head,put}) {
  return {
    async readWorkspace() {
      // Read the write-compatible ETag BEFORE the content. A concurrent write
      // then makes our conditional save fail safely instead of losing changes.
      let metadata;
      try {metadata=await client.head(FILE);}
      catch(e) {if(!(e instanceof BlobNotFoundError))throw e;}
      const content=await client.get(FILE,{access:'private',useCache:false});
      if(content&&!metadata) {
        await content.stream.cancel();
        throw new BlobPreconditionFailedError();
      }
      return {stored:content?metadata:null,state:content?await new Response(content.stream).json():{projects:[],events:[]}};
    },
    async writeWorkspace(stored,state) {
      const data=JSON.stringify(state);
      if(Buffer.byteLength(data)>8_000_000)throw new UserError(413,'Хранилище MVP достигло лимита 8 МБ. Нужна миграция базы.');
      if(stored&&!stored.etag)throw new Error('Missing workspace ETag');
      await client.put(FILE,data,{access:'private',addRandomSuffix:false,contentType:'application/json',cacheControlMaxAge:60,...(stored?{allowOverwrite:true,ifMatch:stored.etag}:{allowOverwrite:false})});
    }
  };
}
