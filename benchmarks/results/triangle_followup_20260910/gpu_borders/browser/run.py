from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
import base64, json, os, subprocess, tempfile, threading, time, urllib.request
from websockets.sync.client import connect
root=Path('/private/tmp/maniml-border-browser-20260910')
class Handler(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  (root/(data.get('page','unknown')+'-report.json')).write_text(json.dumps(data,indent=2))
  self.send_response(200);self.end_headers();self.wfile.write(b'ok')
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(root)))
threading.Thread(target=server.serve_forever,daemon=True).start()
profile=Path(tempfile.mkdtemp(prefix='maniml-border-browser-profile-',dir='/private/tmp'))
args=['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--remote-debugging-port=0','--user-data-dir='+str(profile),'--enable-unsafe-webgpu','--use-angle=metal','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--window-size=1000,750','about:blank']
log=(root/'chrome.log').open('w');chrome=subprocess.Popen(args,stdout=log,stderr=log)
seq=0
failed=[]
try:
 deadline=time.monotonic()+30
 while not (profile/'DevToolsActivePort').exists():
  if chrome.poll() is not None:raise RuntimeError('Chrome exited: '+str(chrome.returncode))
  if time.monotonic()>deadline:raise TimeoutError('Chrome DevTools port not available')
  time.sleep(.1)
 port=int((profile/'DevToolsActivePort').read_text().splitlines()[0])
 targets=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list'))
 target=next(t for t in targets if t['type']=='page')
 with connect(target['webSocketDebuggerUrl'],max_size=32*1024*1024) as ws:
  def call(method,params={}):
   global seq
   seq+=1; ident=seq;ws.send(json.dumps({'id':ident,'method':method,'params':params}))
   while True:
    response=json.loads(ws.recv(timeout=30))
    if response.get('id')==ident:
     if 'error' in response:raise RuntimeError(response['error'])
     return response.get('result',{})
  call('Page.enable');call('Runtime.enable')
  for page in ('direct','player'):
   url=f'http://127.0.0.1:{server.server_port}/'+('' if page=='direct' else 'player/')
   call('Page.navigate',{'url':url})
   deadline=time.monotonic()+90
   while time.monotonic()<deadline:
    value=call('Runtime.evaluate',{'expression':'window.qaResult || null','returnByValue':True}).get('result',{}).get('value')
    if value:
     (root/(page+'-report.json')).write_text(json.dumps(value,indent=2))
     shot=call('Page.captureScreenshot',{'format':'png'})
     (root/(page+'.png')).write_bytes(base64.b64decode(shot['data']))
     print(json.dumps(value),flush=True)
     if value.get('status') != 'PASS': failed.append(page)
     break
    time.sleep(.2)
   else:
    body=call('Runtime.evaluate',{'expression':'document.body.innerText','returnByValue':True})
    raise TimeoutError(page+': '+str(body))
  (root/'environment.json').write_text(json.dumps({'chrome':call('Browser.getVersion'),'flags':args[1:],'url':f'http://127.0.0.1:{server.server_port}','profile':str(profile),'assets':json.loads((root/'source_hashes.json').read_text())},indent=2))
 if failed: raise RuntimeError('Browser QA failed: '+', '.join(failed))
finally:
 chrome.terminate()
 try:chrome.wait(timeout=10)
 except subprocess.TimeoutExpired:chrome.kill();chrome.wait()
 server.shutdown();server.server_close();log.close()
