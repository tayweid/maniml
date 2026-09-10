const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
const base = Buffer.from(fs.readFileSync(0,'utf8'),'base64');
const staticDir = path.join(__dirname,'../maniml/web/static');
const player = fs.readFileSync(path.join(staticDir,'player.js'),'utf8');
const indexer = fs.readFileSync(path.join(staticDir,'geometry_recording.js'),'utf8');
function message(mode, frameId) {
  const length = base.readUInt32LE(1);
  const header = JSON.parse(base.subarray(5,5+length));
  if (frameId !== undefined) header.test_frame = frameId;
  if (mode === null) delete header.renderer; else header.renderer=mode;
  const encoded = Buffer.from(JSON.stringify(header)), output=Buffer.alloc(5+encoded.length);
  output[0]=3; output.writeUInt32LE(encoded.length,1); encoded.copy(output,5);
  return Buffer.concat([output,base.subarray(5+length)]);
}
async function run(format, messages, transformMeta=x=>x) {
  const elements=new Map(), listeners=new Map(), rendered=[], initialized=[], frameIds=[];
  let interval, failNext=false;
  function element() {
    return {children:[], replaceChildren(...children) {this.children=children;},
            appendChild(child) {this.children.push(child);}};
  }
  const data=Buffer.concat(messages);
  const meta=transformMeta({format_version:format, scene:'test', fps:30,
    frames:messages.map(bytes=>({len:bytes.length,segment:0})),segments:1,lines:[1]});
  const driver = name=>({init:async()=>initialized.push(name), render:async frame=>{
    // The real recording materializer must return a complete wire message.
    assert.equal(new Uint8Array(frame)[0],3);
    rendered.push(name);
    const bytes = new Uint8Array(frame);
    const length = new DataView(frame).getUint32(1,true);
    frameIds.push(JSON.parse(new TextDecoder().decode(bytes.subarray(5,5+length))).test_frame);
    if (failNext) {failNext=false; throw new Error('texture decode failed');}
  }});
  const context = {
    console, TextDecoder, TextEncoder, Uint8Array, ArrayBuffer, DataView,
    document:{getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},
              createElement:element,addEventListener(name,handler){listeners.set(name,handler);}},
    fetch:async url=>url==='scene.json'?{json:async()=>meta}:{body:{pipeThrough:value=>value}},
    DecompressionStream:class{}, Response:class{async arrayBuffer(){return data.buffer.slice(data.byteOffset,data.byteOffset+data.length);}},
    setInterval(handler){interval=handler; return 1;},clearInterval(){},
    ManimlWGPU:driver('triangles'),ManimlWindingWGPU:driver('winding'),
  };
  vm.createContext(context);
  vm.runInContext(indexer,context);
  await vm.runInContext(player,context);
  return {elements,listeners,rendered,initialized,frameIds,fail(){failNext=true;},tick:()=>interval()};
}
(async()=>{
  const mode=process.argv[2];
  if(mode==='recovery') {
    const page=await run(3,[message('triangles'),message('triangles')]);
    const unhandled=[];
    process.on('unhandledRejection',error=>unhandled.push(error));
    const seek=()=>page.listeners.get('keydown')({key:'ArrowLeft',shiftKey:true,preventDefault(){}});
    page.fail(); await seek();
    assert.match(page.elements.get('status').textContent,/Playback error: texture decode failed/);
    await seek();
    assert.equal(page.elements.get('status').textContent,'WebGPU');
    page.elements.get('playbtn').onclick(); page.fail(); await page.tick();
    assert.match(page.elements.get('status').textContent,/Playback error/);
    await seek();
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(unhandled.length,0);
    assert.equal(page.rendered.length,5);
  } else if(mode==='segments') {
    const page=await run(3,[0,1,2,3].map(i=>message('triangles',i)),meta=>({
      ...meta,segments:3,lines:[1,2,3],frames:meta.frames.map((frame,i)=>({...frame,segment:[0,1,1,2][i]})),
    }));
    assert.deepEqual(page.frameIds,[0]);
    page.elements.get('chips').children[1].onclick();
    await new Promise(resolve=>setImmediate(resolve));
    assert.deepEqual(page.frameIds,[0,1]);
    await page.tick();
    assert.deepEqual(page.frameIds,[0,1,2]);
    await page.tick();
    assert.deepEqual(page.frameIds,[0,1,2]);
    page.elements.get('chips').children[2].onclick();
    await new Promise(resolve=>setImmediate(resolve));
    assert.deepEqual(page.frameIds,[0,1,2,3]);
    await page.tick();
    assert.deepEqual(page.frameIds,[0,1,2,3]);
  } else if(mode==='formats') {
    for(const [format,renderer,expected] of [[1,null,'winding'],[2,'triangles','triangles'],[2,'winding','winding'],[3,'triangles','triangles'],[3,'winding','winding']]) {
      const page=await run(format,[message(renderer)]);
      assert.deepEqual(page.initialized,[expected]);
      assert.deepEqual(page.rendered,[expected]);
    }
  } else if(mode==='corrupt') {
    const cases=[
      [3,[message('triangles').subarray(0,-1)]],
      [3,[message('unknown')]], [3,[message(null)]],
      [3,[message('triangles'),message('winding')]],
      [3,[message('triangles')],meta=>({...meta,frames:[{len:1,segment:0}]})],
    ];
    for(const args of cases) {
      const page=await run(...args);
      assert.equal(page.initialized.length,0);
      assert.equal(page.elements.get('playbtn').disabled,true);
      assert.equal(page.elements.get('status').textContent,'Recording error');
      assert.match(page.elements.get('stage').children[0].textContent,/Unable to load scene recording/);
    }
  } else throw new Error('Unknown case');
})().catch(error=>{console.error(error);process.exitCode=1;});
