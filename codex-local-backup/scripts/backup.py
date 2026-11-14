#!/usr/bin/env python3
"""Versioned offline Codex backup, content-addressed files, no automatic deletion."""
import argparse,datetime as dt,hashlib,json,os,re,shutil,sqlite3,subprocess,tempfile
from contextlib import contextmanager,closing
from pathlib import Path
from urllib.parse import quote,unquote

BLOCK=8*1024**2
SKIP={'.git','node_modules','.venv','__pycache__','browser-profile'}
SECRET={'auth.json','.env','.env.local','credentials.json','Cookies','Login Data','.DS_Store'}
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(BLOCK),b''):h.update(block)
    return h.hexdigest()
def dump(p,v):
    tmp=p.with_name(p.name+'.tmp')
    tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,p)
def stamp():return dt.datetime.now().astimezone().isoformat()

@contextmanager
def backup_lock(path):
    with path.open('a+b') as f:
        try:
            if os.name=='nt':
                import msvcrt
                if f.seek(0,2)==0:f.write(b'0');f.flush()
                f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as e:raise RuntimeError('Another backup is running or the filesystem cannot lock') from e
        try:yield
        finally:
            if os.name=='nt':f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)

def database(raw,prefix):
    files=[f for f in raw.glob(prefix+'_[0-9]*.sqlite') if re.fullmatch(re.escape(prefix)+r'_\d+\.sqlite',f.name)]
    return max(files,key=lambda f:int(f.stem.rsplit('_',1)[1])) if files else None

@contextmanager
def log_stream(path):
    if path.suffix!='.zst':
        with path.open(encoding='utf-8') as f:yield f
        return
    try:from compression import zstd
    except ImportError:zstd=None
    if zstd:
        with zstd.open(path,mode='rt',encoding='utf-8') as f:yield f
    else:
        if not shutil.which('zstd'):raise RuntimeError('Compressed logs saved, but readable export needs Python 3.14+ or the zstd command')
        proc=subprocess.Popen(['zstd','-dc',str(path)],stdout=subprocess.PIPE,text=True,encoding='utf-8')
        try:
            yield proc.stdout
            if proc.wait():raise RuntimeError('zstd decompression failed')
        finally:
            proc.stdout.close()
            if proc.poll() is None:proc.terminate();proc.wait()

def events(path):
    with log_stream(path) as stream:
        for line in stream:
            try:yield json.loads(line)
            except json.JSONDecodeError:
                if line.endswith('\n'):raise RuntimeError('Invalid JSON in session log: '+str(path))
                # The final line may have been in flight when captured.

def log_rows(raw):
    rows={}
    for folder in ['sessions','archived_sessions']:
        for path in (raw/folder).rglob('*'):
            if not path.is_file():continue
            for event in events(path):
                if event.get('type')=='session_meta':
                    meta=event.get('payload',{});tid=meta.get('id')
                    if tid:rows[tid]={'id':tid,'rollout_path':str(path),'cwd':meta.get('cwd',''),'title':meta.get('title') or tid}
                    break
    return list(rows.values())

class Backup:
    def __init__(self,root,source,min_free,include=()):
        self.root=root;self.source=source;self.min_free=min_free*1024**3
        self.objects=root/'objects';self.objects.mkdir(parents=True,exist_ok=True)
        self.cache_path=root/'file-cache.json'
        self.cache=json.loads(self.cache_path.read_text(encoding='utf-8')) if self.cache_path.exists() else {}
        self.entries=[];self.issues=[];self.excluded=set();self.candidates=set();self.explicit_refs=set()
        self.allowed=[Path.home()/x for x in ['Desktop','Documents','Downloads']]+[source/x for x in ['attachments','generated_images','visualizations','skills']]
        self.allowed.extend(Path(p).expanduser().resolve() for p in include)
    def reserve(self,n):
        if shutil.disk_usage(self.root).free<n+self.min_free:raise OSError('insufficient disk space; reserve floor reached')
    def object(self,sha):return self.objects/sha[:2]/sha
    def ingest(self,src,relative,cache=True):
        try:
            before=src.stat();sig=[before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns]
            cached=self.cache.get(str(src)) if cache else None
            if cached and cached['signature']==sig and self.object(cached['sha256']).is_file():sha=cached['sha256']
            else:
                sha=digest(src);obj=self.object(sha)
                if not obj.exists():
                    self.reserve(before.st_size);obj.parent.mkdir(parents=True,exist_ok=True)
                    fd,tmp=tempfile.mkstemp(dir=obj.parent,prefix='.copy-');os.close(fd);temp=Path(tmp)
                    try:
                        shutil.copyfile(src,temp)
                        if digest(temp)!=sha:raise OSError('source changed during copy')
                        os.replace(temp,obj)
                    finally:temp.unlink(missing_ok=True)
                after=src.stat()
                if [after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns]!=sig:raise OSError('source changed during capture; retry next run')
                if cache:self.cache[str(src)]={'signature':sig,'sha256':sha}
            dest=self.stage/relative;dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists():
                if os.path.samefile(dest,self.object(sha)):return True
                raise OSError('two references resolve to different contents at the same backup path')
            try:os.link(self.object(sha),dest)
            except OSError:
                self.reserve(before.st_size);shutil.copyfile(self.object(sha),dest)
            self.entries.append({'source':str(src),'backup':str(relative),'bytes':before.st_size,'sha256':sha})
            return True
        except Exception as e:
            self.issues.append({'source':str(src),'error':str(e),'backup':str(relative)})
            return False
    @staticmethod
    def excluded_path(p):
        parts={part.lower() for part in p.parts}
        return (
            bool(parts & (SKIP | {'.ssh','.aws','.gnupg','cookies','keychains','chromium','google chrome','firefox','safari','microsoft edge','bravesoftware','browser profiles'}))
            or p.name.lower() in {name.lower() for name in SECRET}
            or p.name.lower().startswith('.env')
            or p.suffix.lower() in {'.pem','.key','.p12','.pfx'}
        )

    def path(self,s,explicit=True):
        if not isinstance(s,str) or len(s)>4096:return
        s=unquote(s.removeprefix('file://')) if s.startswith('file://') else s
        if any(ord(c)<32 for c in s):return
        s=re.sub(r':\d+(?::\d+)?$','',s)
        p=Path(s).expanduser()
        if not p.is_absolute():return
        p=Path(os.path.normpath(p))
        if p.is_relative_to(self.root) or not any(p.is_relative_to(a) for a in self.allowed):return
        if self.excluded_path(p):return
        try:
            resolved=p.resolve()
            if resolved.is_relative_to(self.root.resolve()) or self.excluded_path(resolved):return
            if not any(resolved.is_relative_to(a.resolve()) for a in self.allowed):return
        except (OSError,RuntimeError,ValueError):return
        self.candidates.add(p)
        if explicit:self.explicit_refs.add(p)
    def inspect(self,v):
        if isinstance(v,dict):
            for k,val in v.items():
                self.path(k,explicit=False)
                if k in {'path','file_path','filePath','url'} and isinstance(val,str):self.path(val)
                self.inspect(val)
        elif isinstance(v,list):
            for val in v:self.inspect(val)
        elif isinstance(v,str):
            if v.startswith('data:'):return
            if v.startswith(('/','~/','file:///')) or re.match(r'^[A-Za-z]:[\\/]',v):self.path(v,explicit=False)
            for p in re.findall(r'\]\((?:<)?((?:file://)?/[^\n]*?)(?:>)?\)',v):self.path(p)
            for p in re.findall(r'["\x27`]((?:/Users/|/home/|~/)[^\n"\x27`]+)["\x27`]',v):self.path(p,explicit=False)
            for p in re.findall(r'/(?:Users|home)/[^\s<>"\x27`\[\](){}，。；：]+',v):self.path(p.rstrip('.,;'),explicit=False)
            for p in re.findall(r'[A-Za-z]:[\\/][^\n<>"\x27`|]+',v):self.path(p.rstrip('.,;) '),explicit=False)
    def seed(self,baseline):
        # A verified old backup can populate objects without another full disk copy.
        count=0
        for m in json.loads((baseline/'校验清单.json').read_text(encoding='utf-8')):
            src=baseline/m['backup'];sha=m['sha256'];obj=self.object(sha)
            if src.name=='.DS_Store':continue
            if obj.exists() or not src.is_file():continue
            if digest(src)!=sha:raise RuntimeError('seed checksum mismatch: '+str(src))
            obj.parent.mkdir(parents=True,exist_ok=True)
            # Only link prior backup files, never live source files.
            try:os.link(src,obj)
            except OSError:self.reserve(src.stat().st_size);shutil.copyfile(src,obj)
            count+=1
        dump(self.root/'imported-baseline.json',{'baseline':str(baseline),'entries':json.loads((baseline/'校验清单.json').read_text(encoding='utf-8'))})
        print(json.dumps({'seeded_objects':count}),flush=True)
    def run(self):
        ident=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        self.stage=self.root/'snapshots'/('.partial-'+ident);self.stage.mkdir(parents=True)
        dbs=[p for p in [database(self.source,'state'),database(self.source,'thread_history')] if p]
        for db in dbs:
            name=db.name
            self.reserve((self.source/name).stat().st_size)
            tmp=self.stage/('.'+name)
            with closing(sqlite3.connect((self.source/name).as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(tmp)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('database integrity failed')
            if not self.ingest(tmp,Path('原始记录')/name,cache=False):raise RuntimeError('database capture failed')
            self.entries[-1]['source']=str(self.source/name);tmp.unlink()
        for folder in ['sessions','archived_sessions']:
            for p in sorted((self.source/folder).rglob('*')):
                if p.is_file() and (p.name.endswith('.jsonl') or p.name.endswith('.jsonl.zst')):
                    self.ingest(p,Path('原始记录')/p.relative_to(self.source))
        for name in ['session_index.jsonl','history.jsonl']:
            p=self.source/name
            if p.is_file():self.ingest(p,Path('原始记录')/name)
        raw=self.stage/'原始记录'
        state_path=database(raw,'state');history_path=database(raw,'thread_history')
        rows=[];hist=None
        if state_path:
            con=sqlite3.connect(state_path);con.row_factory=sqlite3.Row
            try:rows=[dict(r) for r in con.execute('SELECT * FROM threads')]
            except sqlite3.Error as e:self.issues.append({'source':str(state_path),'error':'Unsupported state schema: '+str(e)})
            finally:con.close()
        if history_path:
            hist=sqlite3.connect(history_path)
            try:hist.execute('SELECT thread_id,item_type,item_json,rollout_ordinal,created_at_ms,item_id FROM thread_items LIMIT 0')
            except sqlite3.Error as e:
                hist.close();hist=None;self.issues.append({'source':str(history_path),'error':'Unsupported history schema: '+str(e)})
        # Older CLI installations can have session files without either DB.
        if not rows:
            try:rows=log_rows(raw)
            except Exception as e:self.issues.append({'error':str(e),'kind':'legacy_log_discovery'})
        if not rows and not self.entries:raise RuntimeError('No local persisted Codex sessions found')
        for r in rows:
            cwd=Path(r.get('cwd') or self.source).expanduser()
            if cwd.is_absolute() and cwd not in [Path.home(),Path(cwd.anchor),self.source] and not cwd.is_relative_to(self.root):self.allowed.append(cwd)
        read=self.stage/'可读会话';read.mkdir()
        chats=[];log_missing=[]
        for r in rows:
            old=Path(r['rollout_path'])
            try:rel=old.relative_to(raw if old.is_relative_to(raw) else self.source)
            except ValueError:
                parts=old.parts;rel=None
                for folder in ['sessions','archived_sessions']:
                    if folder in parts:rel=Path(*parts[parts.index(folder):]);break
            log=raw/rel if rel else None
            if log is None or not (log.is_file() or Path(str(log)+'.zst').is_file()):log_missing.append(r['id'])
            msgs=[]
            items=hist.execute('SELECT item_type,item_json FROM thread_items WHERE thread_id=? ORDER BY rollout_ordinal,created_at_ms,item_id',(r['id'],)) if hist else []
            for typ,text in items:
                obj=json.loads(text);self.inspect(obj)
                if typ=='userMessage':
                    chunks=[]
                    for c in obj.get('content',[]):
                        if c.get('text'):chunks.append(c['text'])
                        elif c.get('type') in ['image','localImage']:chunks.append('[图片] '+str(c.get('path') or c.get('url') or '详见原始记录'))
                    msgs.append(('用户','\n\n'.join(chunks)))
                elif typ=='agentMessage':msgs.append(('助手',obj.get('text','')))
            if not msgs and log:
                actual=log if log.is_file() else Path(str(log)+'.zst')
                try:
                    for o in events(actual):
                        pl=o.get('payload',{})
                        self.inspect(pl)
                        if o.get('type')=='response_item' and pl.get('type')=='message' and pl.get('role') in ['user','assistant']:
                            self.inspect(pl)
                            chunks=[x.get('text','') for x in pl.get('content',[]) if isinstance(x,dict) and x.get('type') in ['input_text','output_text','text']]
                            msgs.append(('用户' if pl['role']=='user' else '助手','\n\n'.join(chunks)))
                except Exception as e:self.issues.append({'source':str(actual),'error':str(e),'kind':'readable_export'})
            title=r.get('title') or r['id'];filename=re.sub(r'[^A-Za-z0-9_-]','_',r['id'])+'.md'
            with (read/filename).open('w',encoding='utf-8') as f:
                f.write(f'# {title}\n\n会话 ID：`{r["id"]}`\n\n原工作目录：`{r["cwd"]}`\n')
                for role,text in msgs:f.write('\n---\n\n## '+role+'\n\n'+text+'\n')
                if not msgs:f.write('\n未提取到用户/助手消息；原始记录仍保留。\n')
            chats.append({'id':r['id'],'title':title,'messages':len(msgs),'cwd':r['cwd'],'file':'可读会话/'+filename})
        if hist:hist.close()
        for folder in ['attachments','generated_images','visualizations']:
            for p in (self.source/folder).rglob('*'):
                if p.is_file():self.path(str(p))
        # Carry forward concrete file references from prior manifests, so old outputs
        # remain backed up even when newer compacted history omits their links.
        prior=self.root/'latest.json'
        if prior.exists():
            prev=self.root/json.loads(prior.read_text(encoding='utf-8'))['snapshot']/'manifest.json'
            if prev.exists():
                for m in json.loads(prev.read_text(encoding='utf-8')):
                    if m['backup'].startswith('关联文件/') and m.get('source'):self.path(m['source'])
        missing=[];unconfirmed=[]
        for p in sorted(self.candidates):
            try:
                if p.is_file():
                    rel=Path(re.sub(r'[^A-Za-z0-9]','_',p.drive))/Path(*p.parts[1:]) if p.drive else Path(str(p).lstrip('/'))
                    self.ingest(p,Path('关联文件')/rel)
                elif not p.exists():
                    (missing if p in self.explicit_refs else unconfirmed).append(str(p))
            except OSError as e:self.issues.append({'source':str(p),'error':str(e)})
        # The skill itself travels with the archive.
        skill=Path(__file__).resolve().parents[1]
        for p in skill.rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:self.ingest(p,Path('备份技能')/p.relative_to(skill))
        with (self.stage/'会话索引.md').open('w',encoding='utf-8') as f:
            f.write('# 本地会话索引\n\n')
            for c in chats:f.write(f'- [{c["title"].replace("[", "").replace("]", "")}]({quote(c["file"])})（{c["messages"]} 条消息）\n')
        summary={'created_at':stamp(),'source_home':str(self.source),'chats':len(chats),'messages':sum(c['messages'] for c in chats),'raw_logs':sum(m['backup'].startswith(('原始记录/sessions/','原始记录/archived_sessions/')) for m in self.entries),'associated_files':sum(m['backup'].startswith('关联文件/') for m in self.entries),'missing_rollout_threads':log_missing,'unresolved_path_references':missing,'unconfirmed_text_path_references':unconfirmed,'issues':self.issues,'sessions':chats,'status':'complete' if not self.issues and not log_missing else 'partial'}
        dump(self.stage/'summary.json',summary)
        (self.stage/'README.md').write_text('从会话索引.md 阅读历史；summary.json 查看缺失与错误。原始记录含 .jsonl 与 .jsonl.zst，迁移时均须保留。整个定期备份目录应复制到另一存储设备；仅本机同盘备份无法应对硬盘损坏。当前快照不自动等于恢复已验证。原始文件路径保留原样，按 manifest.json 查对应副本。objects 与 snapshots 通过硬链接去重，不要直接编辑备份文件。无自动删除或清理。',encoding='utf-8')
        tracked={m['backup'] for m in self.entries}
        for p in self.stage.rglob('*'):
            if p.is_file() and str(p.relative_to(self.stage)) not in tracked:self.entries.append({'source':None,'backup':str(p.relative_to(self.stage)),'bytes':p.stat().st_size,'sha256':digest(p)})
        dump(self.stage/'manifest.json',self.entries)
        dest=self.stage.with_name(ident);os.replace(self.stage,dest)
        if summary['status']=='complete':dump(self.root/'latest.json',{'snapshot':str(dest.relative_to(self.root)),'created_at':summary['created_at']})
        dump(self.root/'last-run.json',{'snapshot':str(dest.relative_to(self.root)),**{k:v for k,v in summary.items() if k!='sessions'}})
        latest=self.root/'latest.json'
        link=json.loads(latest.read_text(encoding='utf-8'))['snapshot'] if latest.exists() else str(dest.relative_to(self.root))
        (self.root/'README.md').write_text(f'# Codex 定期备份\n\n[打开最新可用会话索引]({quote(link)}/会话索引.md)\n\n本轮状态：{summary["status"]}；时间：{summary["created_at"]}。详细结果见 last-run.json。\n\n保留原始数据库、普通及压缩 session、关联成果和备份技能。objects 存去重内容，snapshots 保存历史；请复制整个目录，不直接编辑其中的文件。不自动删除历史。同盘副本不能防磁盘损坏，建议另存一份到移动硬盘。',encoding='utf-8')
        dump(self.cache_path,self.cache)
        print(json.dumps({'snapshot':str(dest),**{k:summary[k] for k in ['status','chats','messages','raw_logs','associated_files']},'issue_count':len(self.issues),'missing_rollouts':len(log_missing)},ensure_ascii=False),flush=True)
        return 0 if summary['status']=='complete' else 2

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['backup','status','verify']);p.add_argument('--root',type=Path,default=Path.home()/'CodexBackups');p.add_argument('--source',type=Path,default=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex')));p.add_argument('--include',type=Path,action='append',default=[]);p.add_argument('--seed',type=Path);p.add_argument('--min-free-gib',type=float,default=15);p.add_argument('--snapshot',type=Path);p.add_argument('--full',action='store_true');a=p.parse_args()
    a.root=a.root.expanduser().resolve();a.source=a.source.expanduser().resolve()
    if a.action=='backup' and not a.source.is_dir():raise SystemExit('CODEX_HOME/source does not exist')
    if a.root==a.source or a.root.is_relative_to(a.source):raise SystemExit('Backup root must be outside CODEX_HOME')
    a.root.mkdir(parents=True,exist_ok=True,mode=0o700);os.umask(0o077)
    if a.action=='status':
        print((a.root/'last-run.json').read_text(encoding='utf-8') if (a.root/'last-run.json').exists() else '{}');return 0
    if a.action=='verify':
        snap=a.snapshot or a.root/json.loads((a.root/'latest.json').read_text(encoding='utf-8'))['snapshot'];errors=[];entries=json.loads((snap/'manifest.json').read_text(encoding='utf-8'))
        for m in entries:
            f=snap/m['backup']
            if not f.is_file() or f.stat().st_size!=m['bytes'] or (a.full and digest(f)!=m['sha256']):errors.append(m['backup'])
        report={'checked_at':stamp(),'files':len(entries),'mode':'sha256' if a.full else 'size-and-existence','errors':errors}
        dump(snap/('verification-full.json' if a.full else 'verification-quick.json'),report)
        print(json.dumps(report,ensure_ascii=False));return int(bool(errors))
    with backup_lock(a.root/'.backup.lock'):
        b=Backup(a.root,a.source,a.min_free_gib,a.include)
        if a.seed:b.seed(a.seed)
        try:return b.run()
        except Exception as e:
            dump(a.root/'failure.json',{'time':stamp(),'error':str(e)});raise
if __name__=='__main__':raise SystemExit(main())
