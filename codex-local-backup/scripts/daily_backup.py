#!/usr/bin/env python3
"""Local daily entry point; forward backup flags, no model or network calls."""
import datetime,subprocess,sys
from pathlib import Path
script=Path(__file__).with_name('backup.py')
args=sys.argv[1:]
steps=[['backup'],['verify']]
if datetime.datetime.now().weekday()==0:steps.append(['verify','--full'])
for step in steps:
    result=subprocess.run([sys.executable,str(script),*step,*args])
    if result.returncode:raise SystemExit(result.returncode)
