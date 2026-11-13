import os,re,subprocess,pathlib,json,datetime
root=pathlib.Path(r'C:\Users\SCM\Documents\GitHub')
out=root/'Harness'/'.lane-triage'
report=(out/'local-ground-inventory-2026-11-08.txt').read_text(encoding='utf-8',errors='replace')
paths=[]
for line in report.splitlines():
 if line.startswith('WORKTREE '):
  p=pathlib.Path(line[9:].strip())
  try: p.relative_to(root)
  except ValueError: continue
  if p not in paths: paths.append(p)
def git(path,*args):
 try:
  p=subprocess.run(['git','-C',str(path),*args],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
  return p.returncode,p.stdout,p.stderr.strip()
 except Exception as e: return -1,'',str(e)
rows=[]; repositories={}
for p in paths:
 rc,head,err=git(p,'rev-parse','HEAD')
 rc2,branch,_=git(p,'branch','--show-current')
 rc3,status,serr=git(p,'status','--porcelain=v1','--untracked-files=normal')
 rc4,ignored,ierr=git(p,'status','--porcelain=v1','--ignored=matching','--untracked-files=all')
 rc5,common,cerr=git(p,'rev-parse','--path-format=absolute','--git-common-dir')
 key=common.strip() if rc5==0 else 'UNKNOWN '+str(p)
 if key not in repositories:
  rc6,refs,rerr=git(p,'for-each-ref','--format=%(refname:short) %(objectname)','refs/heads')
  repositories[key]={'source':str(p),'refs':refs.splitlines(),'error':rerr if rc6 else ''}
 rows.append({'path':str(p),'head':head.strip() if not rc else 'ERROR '+err,'branch':branch.strip() if not rc2 else 'ERROR','status':status.splitlines(),'status_error':serr if rc3 else '', 'ignored':[x[3:] for x in ignored.splitlines() if x.startswith('!! ')], 'ignored_error':ierr if rc4 else '', 'common':key})
 print('processed',p.name,'ignored',len(rows[-1]['ignored']),flush=True)
raw={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'discovery':'Prior report identified these paths; it recorded access denied at GitHub\\Kalshi-Trader\\release_check_gdehxzxm. Independent clone discovery is incomplete.','rows':rows,'repositories':repositories}
(out/'inventory-two-pass.json').write_text(json.dumps(raw,indent=2,ensure_ascii=False),encoding='utf-8')
lines=['LOCAL GROUND TWO-PASS INVENTORY - draft; read time '+raw['utc'],raw['discovery'],'Method: git rev-parse, branch --show-current, status --porcelain=v1 --untracked-files=normal, and status --porcelain=v1 --ignored=matching --untracked-files=all. Ignored directory entries may still be collapsed by Git; names are not a content or secret review.','']
for row in rows:
 lines += ['PATH '+row['path'],'HEAD '+row['head'],'BRANCH '+(row['branch'] or '(detached)'),'COMMON '+row['common'],'STATUS '+ (' | '.join(row['status']) if row['status'] else '(clean)')]
 if row['status_error']: lines+=['STATUS ERROR '+row['status_error']]
 lines+=['IGNORED '+(' | '.join(row['ignored']) if row['ignored'] else '(none reported)')]
 if row['ignored_error']: lines+=['IGNORED ERROR '+row['ignored_error']]
 lines+=['']
for key,repo in repositories.items():
 lines+=['LOCAL BRANCH REFS common='+key+' source='+repo['source']]+repo['refs']+(['ERROR '+repo['error']] if repo['error'] else [])+['']
text='\n'.join(lines)
(out/'inventory-two-pass.txt').write_text(text,encoding='utf-8')
# GitHub limit applies to characters. Split long lines safely as well as ordinary lines.
chunks=[text[i:i+45000] for i in range(0,len(text),45000)]
for i,chunk in enumerate(chunks,1): (out/f'inventory-two-pass-part-{i:03}.txt').write_text(chunk,encoding='utf-8')
print('paths',len(rows),'common repos',len(repositories),'chars',len(text),'chunks',len(chunks),flush=True)
