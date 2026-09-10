from pathlib import Path
root=Path('/private/tmp/maniml-border-browser-20260910')
archive=Path(__file__).resolve().parent
(root/'index.html').write_bytes((archive/'direct.html').read_bytes())
(root/'observer.js').write_bytes((archive/'observer.js').read_bytes())
player=root/'player';(player/'observer.js').write_bytes((root/'observer.js').read_bytes())
text=(root/'player.html').read_text().replace('<head>','<head><script src="observer.js"></script>')
wrapper='''<script>
qa.draws=[];
const render=ManimlWGPU.render;
ManimlWGPU.render=async function(frame){const result=await render.call(this,frame);const canvas=document.querySelector('#stage canvas');const rgba=await pixels(canvas);qa.draws.push({name:header(frame).test_frame,pixel:center(rgba,canvas)});return result;};
ManimlWGPU.onCacheMiss=()=>qa.cacheMisses++;
</script>'''
text=text.replace('<script src="player.js">',wrapper+'<script src="player.js">')
check='''<script>
const report=document.createElement('pre');report.id='report';report.style='position:fixed;left:8px;top:8px;z-index:100;background:#101620;color:white;padding:12px;white-space:pre-wrap';document.body.appendChild(report);
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function until(test,label){for(let i=0;i<400;i++){if(test())return;await delay(25);}throw new Error('Timeout: '+label);}
async function chip(index,name){const before=qa.draws.length;document.getElementById('chips').children[index].click();await until(()=>qa.draws.length>before&&qa.draws.at(-1).name===name,'chip '+index);}
(async()=>{
 await until(()=>qa.draws.length&&document.getElementById('chips').children.length===8,'boot');
 assert(qa.draws[0].name==='paint-red','initial frame skipped');
 await chip(7,'border-zoom');await chip(1,'paint-blue');await chip(2,'paint-empty');await chip(3,'border-green');
 await chip(6,'border-return');await until(()=>document.getElementById('playbtn').textContent==='▶','single frame stopped');
 const before=qa.draws.length;document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',shiftKey:true,bubbles:true}));
 await until(()=>qa.draws.length>before&&qa.draws.at(-1).name==='border-empty','random backward');
 await chip(0,'paint-red-cached');await until(()=>document.getElementById('playbtn').textContent==='▶','first segment stopped');
 const start=qa.draws.length;document.getElementById('playbtn').click();
 await until(()=>qa.draws.length>start+6&&qa.draws.at(-1).name==='border-zoom','forward playback');
 await until(()=>document.getElementById('playbtn').textContent==='▶','playback stopped');
 const reverse=qa.draws.length;document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
 await until(()=>qa.draws.length>reverse&&qa.draws.at(-1).name==='border-return','reverse playback');
 for(const draw of qa.draws){if(draw.name.startsWith('paint-')){const expected=draw.name.includes('empty')?'0,0,0,255':draw.name.includes('blue')?'0,0,255,255':'255,0,0,255';assert(String(draw.pixel)===expected,'player paint mismatch '+draw.name);}}
 assert(!qa.errors.length&&!qa.cacheMisses,'player validation error or cache miss');
 await finish({status:'PASS',page:'player',frames:qa.draws.length,draws:qa.draws,cases:['production player format5 containing format4 paint and format5 border frames','first and single-frame segments','forward and reverse playback','random backward seek','empty and returning geometry','independent paint and border rehydration','actual GPU canvas pixel probes']});
})().catch(error=>finish({status:'FAIL',page:'player',error:error.stack,draws:qa.draws}));
</script>'''
(player/'index.html').write_text(text.replace('</body>',check+'</body>'))
