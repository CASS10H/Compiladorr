#!/usr/bin/env python3
"""Universal project builder. Detects common project types and runs their native build tools."""
from __future__ import annotations
import json, os, shutil, subprocess, traceback, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ZIP_FILE=ROOT/'input/project.zip'; WORK=ROOT/'work/project'; OUT=ROOT/'artifacts'; LOG_DIR=OUT/'logs'; LOG_FILE=LOG_DIR/'build.log'

def log(s):
 print(s,flush=True); LOG_DIR.mkdir(parents=True,exist_ok=True)
 with LOG_FILE.open('a',encoding='utf-8') as f:f.write(s+'\n')
def run(cmd,cwd,env=None):
 log('$ '+' '.join(map(str,cmd)))
 with LOG_FILE.open('a',encoding='utf-8') as f:
  p=subprocess.Popen(list(map(str,cmd)),cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace')
  for line in p.stdout:
   print(line,end='',flush=True); f.write(line)
  code=p.wait()
 if code: raise subprocess.CalledProcessError(code,cmd)
def extract():
 if not ZIP_FILE.is_file(): raise FileNotFoundError('Coloque o projeto compactado em input/project.zip')
 if WORK.exists():shutil.rmtree(WORK)
 WORK.mkdir(parents=True)
 with zipfile.ZipFile(ZIP_FILE) as z:
  for e in z.infolist():
   n=e.filename.replace('\\','/'); dest=(WORK/n).resolve()
   if n.startswith('/') or (len(n)>1 and n[1]==':') or (dest!=WORK.resolve() and WORK.resolve() not in dest.parents):raise RuntimeError('Caminho inseguro no ZIP: '+e.filename)
  z.extractall(WORK)
 # Ignore common metadata when detecting a single enclosing directory.
 entries=[x for x in WORK.iterdir() if x.name not in ('__MACOSX',)]
 if len(entries)==1 and entries[0].is_dir():
  nested=entries[0]
  for x in list(nested.iterdir()):shutil.move(str(x),str(WORK/x.name))
  nested.rmdir()
 return WORK

def config(project):
 p=project/'build.json'
 if p.exists():
  data=json.loads(p.read_text(encoding='utf-8'))
  if not isinstance(data,dict):raise ValueError('build.json precisa conter um objeto JSON')
  return data
 return {}
def has(p,*names):return any((p/n).exists() for n in names)
def detect(p,cfg):
 explicit=cfg.get('type','').lower()
 if explicit:return explicit
 if has(p,'gradlew','settings.gradle','settings.gradle.kts','build.gradle','build.gradle.kts'):
  if has(p,'pubspec.yaml') and has(p,'android'):return 'flutter'
  return 'android-gradle' if has(p,'app/src/main/AndroidManifest.xml') else 'gradle'
 if has(p,'pubspec.yaml'):return 'flutter'
 if has(p,'package.json'):
  d=json.loads((p/'package.json').read_text(encoding='utf-8')); scripts=d.get('scripts',{})
  return 'node' if scripts.get('build') else 'node-install'
 if has(p,'CMakeLists.txt'):return 'cmake'
 if has(p,'Cargo.toml'):return 'rust'
 if any(p.glob('*.sln')) or any(p.glob('*.csproj')):return 'dotnet'
 if has(p,'pyproject.toml','requirements.txt','setup.py'):return 'python'
 if has(p,'index.html'):return 'static-web'
 raise RuntimeError('Tipo não identificado. Adicione build.json com o campo type e instruções compatíveis.')
def build(p,cfg):
 kind=detect(p,cfg); log('Tipo detectado: '+kind)
 custom=cfg.get('commands')
 if custom:
  if not isinstance(custom,list) or not all(isinstance(x,list) and x for x in custom):raise ValueError('build.json: commands deve ser lista de listas de argumentos')
  for cmd in custom:run(cmd,p)
 elif kind in ('android-gradle','gradle'):
  gradlew=p/('gradlew.bat' if os.name=='nt' else 'gradlew'); gradle=str(gradlew) if gradlew.exists() else shutil.which('gradle')
  if not gradle:raise RuntimeError('Gradle não encontrado')
  if gradlew.exists():gradlew.chmod(0o755)
  task=cfg.get('task','assembleDebug' if kind=='android-gradle' else 'build')
  run([gradle,'--no-daemon','--stacktrace',task],p)
 elif kind=='flutter':
  run(['flutter','pub','get'],p); run(['flutter','build',cfg.get('target','apk'),'--release'],p)
 elif kind in ('node','node-install'):
  lock=has(p,'package-lock.json'); yarn=has(p,'yarn.lock'); pnpm=has(p,'pnpm-lock.yaml')
  if pnpm:run(['corepack','pnpm','install','--frozen-lockfile'],p)
  elif yarn:run(['corepack','yarn','install','--immutable'],p)
  elif lock:run(['npm','ci'],p)
  else:run(['npm','install'],p)
  if kind=='node':run(['npm','run',cfg.get('script','build')],p)
 elif kind=='cmake':
  b=p/'build'; b.mkdir(exist_ok=True); run(['cmake','-S',p,'-B',b,'-DCMAKE_BUILD_TYPE=Release'],p); run(['cmake','--build',b,'--config','Release','--parallel'],p)
 elif kind=='rust':run(['cargo','build','--release'],p)
 elif kind=='dotnet':run(['dotnet','build',cfg.get('project','.'),'-c','Release'],p)
 elif kind=='python':
  if has(p,'requirements.txt'):run(['python','-m','pip','install','-r','requirements.txt'],p)
  if has(p,'pyproject.toml','setup.py'):run(['python','-m','pip','install','.'],p)
  if cfg.get('commands') is None:log('Dependências Python instaladas; nenhum comando de empacotamento foi definido.')
 elif kind=='static-web':log('Site estático detectado; arquivos prontos para publicação.')
 else:raise RuntimeError('Tipo não suportado: '+kind)
 return kind

def collect(p):
 dest=OUT/'output';
 if dest.exists():shutil.rmtree(dest)
 dest.mkdir(parents=True)
 patterns=['*.apk','*.aab','*.ipa','*.exe','*.msi','*.app','*.deb','*.rpm','*.zip','*.tar.gz','*.whl','*.jar','*.war','*.wasm']
 found=[]
 for pattern in patterns:
  for f in p.rglob(pattern):
   if any(x in f.parts for x in ('.gradle','node_modules','.git')):continue
   target=dest/f.name
   if not target.exists():shutil.copy2(f,target);found.append(target.name)
 # Web output folders commonly produced by frontend frameworks.
 for folder in ('dist','build','out','release'):
  d=p/folder
  if d.is_dir() and not any(x in d.parts for x in ('node_modules',)):
   target=dest/folder
   if not target.exists():shutil.copytree(d,target);found.append(folder+'/')
 return found

def main():
 OUT.mkdir(exist_ok=True); LOG_DIR.mkdir(exist_ok=True)
 if LOG_FILE.exists():LOG_FILE.unlink()
 try:
  log('=== COMPILADOR UNIVERSAL ==='); p=extract(); cfg=config(p); kind=build(p,cfg); files=collect(p)
  summary='Resultado: SUCESSO\nTipo: '+kind+'\nArquivos coletados: '+(', '.join(files) if files else 'Nenhum artefato reconhecido; consulte o log.')+'\n'
  (OUT/'build-summary.txt').write_text(summary,encoding='utf-8');log(summary.strip())
 except Exception as e:
  details=f'{type(e).__name__}: {e}\n\n{traceback.format_exc()}';(OUT/'build-error.txt').write_text(details,encoding='utf-8');log('FALHA: '+str(e));raise
if __name__=='__main__':main()
