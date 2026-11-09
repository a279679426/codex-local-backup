#!/usr/bin/env python3
"""Synthetic regression tests; never access the user's real Codex records."""
import json,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path

SCRIPT=Path(__file__).with_name('backup.py')
TID='00000000-0000-4000-8000-000000000001'

class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='codex-backup-test-')
        self.base=Path(self.tmp.name).resolve();self.source=self.base/'source';self.source.mkdir();self.root=self.base/'backup'
    def tearDown(self):self.tmp.cleanup()
    def run_backup(self,action='backup',*extra):
        return subprocess.run([sys.executable,str(SCRIPT),action,'--source',str(self.source),'--root',str(self.root),'--min-free-gib','0',*extra],capture_output=True,text=True,encoding='utf-8')
    def latest(self):return self.root/json.loads((self.root/'latest.json').read_text(encoding='utf-8'))['snapshot']
    def make_log(self,compressed=False):
        p=self.source/'sessions'/'test.jsonl';p.parent.mkdir(exist_ok=True)
        content='\n'.join(json.dumps(o) for o in [
            {'type':'session_meta','payload':{'id':TID,'cwd':str(self.base)}},
            {'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'hello'}]}},
            {'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'world'}]}}
        ])+'\n'
        if compressed:
            from backup import log_stream
            try:from compression import zstd
            except ImportError:self.skipTest('Compressed roundtrip test needs Python 3.14+; command fallback is tested by real restore')
            p=Path(str(p)+'.zst');p.write_bytes(zstd.compress(content.encode()))
        else:p.write_text(content,encoding='utf-8')
        return p
    def modern(self):
        log=self.make_log()
        c=sqlite3.connect(self.source/'state_7.sqlite');c.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT,title TEXT,cwd TEXT)');c.execute('INSERT INTO threads VALUES(?,?,?,?)',(TID,str(log),'Synthetic session',str(self.base)));c.commit();c.close()
        c=sqlite3.connect(self.source/'thread_history_2.sqlite');c.execute('CREATE TABLE thread_items(thread_id TEXT,item_type TEXT,item_json TEXT,rollout_ordinal INTEGER,created_at_ms INTEGER,item_id TEXT)');c.execute('INSERT INTO thread_items VALUES(?,?,?,?,?,?)',(TID,'userMessage',json.dumps({'content':[{'type':'text','text':'hello'}]}),1,1,'one'));c.commit();c.close()
        return log
    def test_legacy_without_databases(self):
        self.make_log();r=self.run_backup();self.assertEqual(r.returncode,0,r.stderr+r.stdout)
        summary=json.loads((self.latest()/'summary.json').read_text(encoding='utf-8'));self.assertEqual(summary['chats'],1);self.assertEqual(summary['messages'],2)
    def test_compressed_legacy_without_databases(self):
        self.make_log(True);r=self.run_backup();self.assertEqual(r.returncode,0,r.stderr+r.stdout)
        self.assertTrue((self.latest()/'原始记录/sessions/test.jsonl.zst').exists())
        self.assertIn('world',(self.latest()/'可读会话'/f'{TID}.md').read_text(encoding='utf-8'))
    def test_daily_runner_keeps_source_unchanged(self):
        log=self.make_log();before=log.read_bytes()
        result=subprocess.run([sys.executable,str(SCRIPT.with_name('daily_backup.py')),'--source',str(self.source),'--root',str(self.root),'--min-free-gib','0'],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertEqual(log.read_bytes(),before)
        self.assertTrue((self.latest()/'verification-quick.json').exists())
    def test_versions_secrets_and_corruption(self):
        log=self.modern();asset=self.source/'attachments'/'photo.txt';asset.parent.mkdir();asset.write_text('first')
        (asset.parent/'.env.production').write_text('never export')
        r=self.run_backup();self.assertEqual(r.returncode,0,r.stderr+r.stdout);first=self.latest()
        asset.write_text('second');r=self.run_backup();self.assertEqual(r.returncode,0,r.stderr+r.stdout);second=self.latest()
        manifest=json.loads((second/'manifest.json').read_text(encoding='utf-8'));entry=next(m for m in manifest if m['source']==str(asset));relative=entry['backup']
        self.assertEqual((first/relative).read_text(),'first');self.assertEqual((second/relative).read_text(),'second')
        self.assertFalse(any('.env.production' in m['backup'] for m in manifest))
        self.assertEqual(self.run_backup('verify','--full').returncode,0)
        (second/relative).write_text('corrupted');self.assertEqual(self.run_backup('verify','--full').returncode,1)
        log.unlink();r=self.run_backup();self.assertEqual(r.returncode,2);self.assertEqual(self.latest(),second)

if __name__=='__main__':unittest.main()
