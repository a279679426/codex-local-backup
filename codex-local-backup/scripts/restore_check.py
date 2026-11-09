#!/usr/bin/env python3
"""Offline restore smoke test. Never starts a model turn or touches live state."""
from pathlib import Path,PureWindowsPath
import argparse,ctypes,json,os,queue,shutil,sqlite3,subprocess,sys,tempfile,threading,time
from backup import database,log_rows

parser=argparse.ArgumentParser();parser.add_argument('--snapshot',type=Path,required=True);args=parser.parse_args()
BACKUP=args.snapshot.resolve()
TEST=Path(tempfile.mkdtemp(prefix='codex-restore-test-'))
REPORT=BACKUP/'restore-check.json'
clonefile=None
if sys.platform=='darwin':
    lib=ctypes.CDLL(None,use_errno=True)
    clonefile=lib.clonefile
    clonefile.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int]
def clone(src,dst):
    dst.parent.mkdir(parents=True,exist_ok=True)
    if clonefile and clonefile(os.fsencode(src),os.fsencode(dst),0)==0:return
    if shutil.disk_usage(TEST).free<src.stat().st_size+2*1024**3:raise OSError('Insufficient free space for isolated restore test')
    shutil.copyfile(src,dst)

def rehome(old):
    parts=PureWindowsPath(old).parts if '\\' in old else Path(old).parts
    for folder in ['sessions','archived_sessions']:
        if folder in parts:return TEST/Path(*parts[parts.index(folder):])
    return None

proc=None
result={'scope':'本机相同 Codex 版本、独立 CODEX_HOME；未调用 turn/start，未验证模型生成或新电脑桌面界面','samples':[]}
try:
    for src in (BACKUP/'原始记录').rglob('*'):
        if src.is_file() and (src.suffix=='.sqlite' or 'sessions' in src.parts or 'archived_sessions' in src.parts):
            clone(src,TEST/src.relative_to(BACKUP/'原始记录'))
    state=database(TEST,'state')
    if state:
        con=sqlite3.connect(state);con.row_factory=sqlite3.Row
        rows=[dict(r) for r in con.execute('SELECT * FROM threads')]
        for r in rows:
            path=rehome(r['rollout_path'])
            if path:con.execute('UPDATE threads SET rollout_path=? WHERE id=?',(str(path),r['id']))
        con.commit();con.close()
    else:rows=log_rows(TEST)
    # Force a local file auth store. No credentials copied into the isolated home.
    (TEST/'config.toml').write_text('cli_auth_credentials_store = "file"\nmcp_oauth_credentials_store = "file"\n[analytics]\nenabled = false\n')
    env=os.environ.copy();env['CODEX_HOME']=str(TEST)
    for key in ['CODEX_SQLITE_HOME','CODEX_INTERNAL_ORIGINATOR_OVERRIDE','OPENAI_API_KEY']:
        env.pop(key,None)
    logs=(TEST/'stderr.log').open('w')
    executable=shutil.which('codex')
    if not executable:raise RuntimeError('codex executable not found on PATH; configure PATH before testing')
    proc=subprocess.Popen([executable,'app-server','--listen','stdio://'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=logs,text=True,encoding='utf-8',env=env,cwd=TEST)
    messages=queue.Queue()
    def reader():
        for line in proc.stdout:
            try:messages.put(json.loads(line))
            except json.JSONDecodeError:pass
    threading.Thread(target=reader,daemon=True).start()
    next_id=0
    def send(v):
        proc.stdin.write(json.dumps(v)+'\n');proc.stdin.flush()
    def rpc(method,params,timeout=35):
        global next_id
        next_id+=1;rid=next_id
        send({'id':rid,'method':method,'params':params})
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:m=messages.get(timeout=max(.01,end-time.monotonic()))
            except queue.Empty:break
            if m.get('id')==rid:return m
        return {'error':{'message':'timeout','method':method}}
    init=rpc('initialize',{'clientInfo':{'name':'local_backup_restore_check','version':'1.0.0'}})
    result['initialized']='result' in init
    if 'error' in init:raise RuntimeError(init['error'])
    send({'method':'initialized','params':{}})
    result['codex_version']=subprocess.check_output([executable,'--version'],text=True,encoding='utf-8').strip()
    # Read only the restored snapshot, never live state.
    chosen=[]
    for r in rows:
        local=rehome(r['rollout_path'])
        chosen.append((r,bool(local and local.is_file())))
    for r,has_log in chosen:
        sample={'id':r['id'],'has_uncompressed_log':has_log}
        for method,params in [
            ('thread/read',{'threadId':r['id']}),
            ('thread/turns/list',{'threadId':r['id'],'limit':1}),
            ('thread/resume',{'threadId':r['id'],'excludeTurns':True,'cwd':str(TEST),'approvalPolicy':'never','sandbox':'read-only'})]:
            response=rpc(method,params)
            if method=='thread/resume' and 'archived' in response.get('error',{}).get('message',''):
                unarchive=rpc('thread/unarchive',{'threadId':r['id']})
                sample['isolated_unarchive']={'ok':'result' in unarchive,'error':unarchive.get('error')}
                if 'result' in unarchive:
                    response=rpc(method,params)
            data=response.get('result',{})
            sample[method]={'ok':'result' in response,'error':response.get('error'),'result_keys':list(data)}
            if isinstance(data.get('data'),list):sample[method]['returned_records']=len(data['data'])
        result['samples'].append(sample)
        if not sample['thread/resume']['ok']:
            print(json.dumps(sample,ensure_ascii=False),flush=True)
    result['summary']={method:sum(s[method]['ok'] for s in result['samples']) for method in ['thread/read','thread/turns/list','thread/resume']}
    print(json.dumps(result['summary']),flush=True)
except Exception as e:
    result['test_error']=str(e)
finally:
    if proc:
        proc.terminate()
        try:proc.wait(timeout=8)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
    try:logs.close()
    except Exception:pass
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.rmtree(TEST)
    print('Report: '+str(REPORT),flush=True)
if result.get('test_error') or not result.get('samples') or any(not all(s.get(method,{}).get('ok') for method in ['thread/read','thread/turns/list','thread/resume']) for s in result.get('samples',[])):
    raise SystemExit(2)
