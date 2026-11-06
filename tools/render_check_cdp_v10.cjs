/* Isolated, local fixture only. No existing browser profiles or tabs are touched. */
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const {pathToFileURL}=require('node:url');
const directory=process.argv[2],fixture=path.join(directory,'fixture.html');
const profile=path.join(directory,'profile');
const browser=spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',[
 '--headless=new','--disable-gpu','--no-first-run','--disable-background-networking','--disable-component-update',
 '--disable-sync','--no-default-browser-check','--force-device-scale-factor=1','--remote-debugging-address=127.0.0.1',
 '--remote-debugging-port=0','--user-data-dir='+profile,'--host-resolver-rules=MAP * ~NOTFOUND','about:blank'
],{windowsHide:true,stdio:'ignore'});
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let socket;
(async()=>{
 try{
  let port;
  for(let i=0;i<100;i++){const file=path.join(profile,'DevToolsActivePort');if(fs.existsSync(file)){port=Number(fs.readFileSync(file,'utf8').split('\n')[0]);break;}await wait(100);}
  if(!port)throw Error('Isolated Chrome did not become ready');
  const targets=await (await fetch('http://127.0.0.1:'+port+'/json/list')).json();
  socket=new WebSocket(targets.find(target=>target.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
  let sequence=0;const pending=new Map(),errors=[];
  socket.addEventListener('message',event=>{const value=JSON.parse(event.data);if(value.method==='Runtime.exceptionThrown')errors.push(value.params.exceptionDetails);if(value.id){const request=pending.get(value.id);if(request){pending.delete(value.id);value.error?request.reject(Error(JSON.stringify(value.error))):request.resolve(value.result);}}});
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
  await send('Page.enable');await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:336,height:620,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:pathToFileURL(fixture).href});
  let status='';
  for(let i=0;i<120;i++){await wait(200);const value=await send('Runtime.evaluate',{expression:'document.documentElement.dataset.offlineResult||""',returnByValue:true});status=value.result?.value||'';if(status)break;}
  const screenshot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  fs.writeFileSync(path.join(directory,'renderer.png'),Buffer.from(screenshot.data,'base64'));
  const dom=await send('Runtime.evaluate',{expression:'document.documentElement.outerHTML',returnByValue:true});
  fs.writeFileSync(path.join(directory,'dom.html'),dom.result.value,'utf8');
  fs.writeFileSync(path.join(directory,'report.json'),JSON.stringify({status:status||'FAIL timeout',errors},null,2));
  console.log(status||'FAIL timeout');
  console.log('Evidence: '+directory);
  process.exitCode=status.startsWith('PASS')&&errors.length===0?0:1;
 }catch(error){console.error(error.message);process.exitCode=1;}
 finally{if(socket)socket.close();browser.kill();}
})();
