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
function paintMessage(color, frameId, {cached=false, inline=false, definition=true, empty=false}={}) {
  const length=base.readUInt32LE(1), header=JSON.parse(base.subarray(5,5+length));
  header.renderer='triangles'; header.format_version=inline?3:4; header.test_frame=frameId;
  let raw=empty||cached?Buffer.alloc(0):base.subarray(5+length);
  if(empty) header.batches=[];
  else {
    const batch=header.batches[0]; batch.pipeline='paint';
    if(cached) {batch.cached=true; delete batch.offset; delete batch.index_offset;}
    const paint=Array(24).fill(0); paint[3]=paint[4]=paint[9]=1;
    paint.splice(12,4,...color);
    if(inline) batch.paint=paint;
    else {
      // Synthetic content ids isolate the consumer ABI; encoder digest
      // correctness is exercised by the Python wire tests.
      const hash=(color[0]===1?'a':'b').repeat(32);
      batch.paint_hash=hash; header.paint_data={};
      if(definition) {
        const data=Buffer.alloc(96); paint.forEach((value,i)=>data.writeFloatLE(value,i*4));
        header.paint_data[hash]={offset:raw.length,nbytes:data.length};
        raw=Buffer.concat([raw,data]);
      }
    }
  }
  const encoded=Buffer.from(JSON.stringify(header)), output=Buffer.alloc(5+encoded.length);
  output[0]=3; output.writeUInt32LE(encoded.length,1); encoded.copy(output,5);
  return Buffer.concat([output,raw]);
}
function borderMessage(color, frameId, {cached=false, definition=true, empty=false}={}) {
  const length=base.readUInt32LE(1), header=JSON.parse(base.subarray(5,5+length));
  header.renderer='triangles'; header.format_version=5; header.test_frame=frameId;
  header.paint_data={}; header.border_data={};
  let raw=Buffer.alloc(0);
  if(empty) header.batches=[];
  else {
    const batch=header.batches[0], fillCount=batch.num_verts;
    const original=base.subarray(5+length), fill=original.subarray(batch.offset,batch.offset+fillCount*40);
    const fillIndices=original.subarray(batch.index_offset,batch.index_offset+batch.index_count*4);
    const tail=Buffer.alloc(186*4);
    for(let step=0;step<31;step++) [0,1,2,1,2,3].forEach((corner,i)=>
      tail.writeUInt32LE(fillCount+step*2+corner,(step*6+i)*4));
    const hash=(color[0]===1?'c':'d').repeat(32);
    Object.assign(batch,{pipeline:'surface',fill_num_verts:fillCount,num_verts:fillCount+64,
      count:batch.index_count+186,index_count:batch.index_count+186,border:{hash,num_curves:1}});
    if(cached) {batch.cached=true; delete batch.offset; delete batch.index_offset;}
    else {batch.offset=0; batch.index_offset=fill.length; raw=Buffer.concat([fill,fillIndices,tail]);}
    if(definition) {
      const data=Buffer.alloc(176); data.writeFloatLE(1,37*4);
      color.forEach((value,i)=>data.writeFloatLE(value,(40+i)*4));
      header.border_data[hash]={offset:raw.length,nbytes:data.length}; raw=Buffer.concat([raw,data]);
    }
  }
  const encoded=Buffer.from(JSON.stringify(header)), output=Buffer.alloc(5+encoded.length);
  output[0]=3; output.writeUInt32LE(encoded.length,1); encoded.copy(output,5);
  return Buffer.concat([output,raw]);
}
async function run(format, messages, transformMeta=x=>x) {
  const elements=new Map(), listeners=new Map(), rendered=[], initialized=[], frameIds=[], paintColors=[], borderColors=[];
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
    const header=JSON.parse(new TextDecoder().decode(bytes.subarray(5,5+length)));
    frameIds.push(header.test_frame);
    paintColors.push(header.batches.flatMap(batch=>{
      if(batch.paint_hash) {
        const info=header.paint_data?.[batch.paint_hash];
        assert.ok(info,'every requested frame must carry its own paint definition');
        const values=new DataView(frame,5+length+info.offset,info.nbytes);
        return [Array.from({length:4},(_,i)=>values.getFloat32(48+4*i,true))];
      }
      return batch.paint?[batch.paint.slice(12,16)]:[];
    }));
    borderColors.push(header.batches.flatMap(batch=>{
      if(!batch.border) return [];
      const info=header.border_data?.[batch.border.hash];
      assert.ok(info,'every requested frame must carry its own border definition');
      assert.equal(batch.index_offset-batch.offset,batch.fill_num_verts*40);
      assert.equal(batch.num_verts,batch.fill_num_verts+64*batch.border.num_curves);
      const values=new DataView(frame,5+length+info.offset,info.nbytes);
      return [Array.from({length:4},(_,i)=>values.getFloat32((40+i)*4,true))];
    }));
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
  return {elements,listeners,rendered,initialized,frameIds,paintColors,borderColors,fail(){failNext=true;},tick:()=>interval()};
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
    for(const [format,renderer,expected] of [[1,null,'winding'],[2,'triangles','triangles'],[2,'winding','winding'],[3,'triangles','triangles'],[3,'winding','winding'],[4,'triangles','triangles'],[4,'winding','winding'],[5,'triangles','triangles'],[5,'winding','winding']]) {
      const page=await run(format,[message(renderer)]);
      assert.deepEqual(page.initialized,[expected]);
      assert.deepEqual(page.rendered,[expected]);
    }
    const future=await run(6,[message('triangles')]);
    assert.equal(future.initialized.length,0);
    assert.equal(future.elements.get('status').textContent,'Re-export required');
  } else if(mode==='paint') {
    const red=[1,0,0,1],blue=[0,0,1,1];
    const page=await run(4,[paintMessage(red,0),paintMessage(red,1,{cached:true,definition:false}),
      paintMessage(red,2,{empty:true}),paintMessage(blue,3),paintMessage(blue,4,{cached:true,definition:false})],
      meta=>({...meta,segments:3,lines:[1,2,3],frames:meta.frames.map((frame,i)=>({...frame,segment:[0,0,1,2,2][i]}))}));
    assert.deepEqual(page.paintColors,[[red]]);
    page.elements.get('chips').children[2].onclick();
    await new Promise(resolve=>setImmediate(resolve));
    assert.deepEqual(page.paintColors.at(-1),[blue]);
    const seek=()=>page.listeners.get('keydown')({key:'ArrowLeft',shiftKey:true,preventDefault(){}});
    await seek(); assert.deepEqual(page.paintColors.at(-1),[]);
    await seek(); assert.deepEqual(page.paintColors.at(-1),[red]);
    const unhandled=[];
    process.on('unhandledRejection',error=>unhandled.push(error));
    page.fail(); await seek();
    assert.match(page.elements.get('status').textContent,/Playback error/);
    await seek();
    assert.deepEqual(page.paintColors.at(-1),[red]);
    assert.equal(page.elements.get('status').textContent,'WebGPU');
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(unhandled.length,0);
    const legacy=await run(3,[paintMessage(red,0,{inline:true}),paintMessage(blue,1,{inline:true,cached:true})]);
    legacy.elements.get('playbtn').onclick(); await legacy.tick();
    assert.deepEqual(legacy.paintColors.at(-1),[blue]);
  } else if(mode==='border') {
    const red=[1,0,0,1],blue=[0,0,1,1];
    const page=await run(5,[borderMessage(red,0),borderMessage(red,1,{cached:true,definition:false}),
      borderMessage(red,2,{empty:true}),borderMessage(blue,3),borderMessage(blue,4,{cached:true,definition:false})],
      meta=>({...meta,segments:3,lines:[1,2,3],frames:meta.frames.map((frame,i)=>({...frame,segment:[0,0,1,2,2][i]}))}));
    assert.deepEqual(page.borderColors,[[red]]);
    page.elements.get('chips').children[2].onclick();
    await new Promise(resolve=>setImmediate(resolve));
    assert.deepEqual(page.borderColors.at(-1),[blue]);
    await page.tick(); assert.deepEqual(page.borderColors.at(-1),[blue]);
    const seek=()=>page.listeners.get('keydown')({key:'ArrowLeft',shiftKey:true,preventDefault(){}});
    await seek(); assert.deepEqual(page.borderColors.at(-1),[]);
    await seek(); assert.deepEqual(page.borderColors.at(-1),[red]);
    const unhandled=[];
    process.on('unhandledRejection',error=>unhandled.push(error));
    page.fail(); await seek();
    assert.match(page.elements.get('status').textContent,/Playback error/);
    await seek(); assert.deepEqual(page.borderColors.at(-1),[red]);
    assert.equal(page.elements.get('status').textContent,'WebGPU');
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(unhandled.length,0);
  } else if(mode==='corrupt') {
    const cases=[
      [3,[message('triangles').subarray(0,-1)]],
      [3,[message('unknown')]], [3,[message(null)]],
      [3,[message('triangles'),message('winding')]],
      [3,[message('triangles')],meta=>({...meta,frames:[{len:1,segment:0}]})],
      [4,[paintMessage([1,0,0,1],0,{definition:false})]],
      [4,[paintMessage([1,0,0,1],0).subarray(0,-1)]],
      [5,[borderMessage([1,0,0,1],0,{definition:false})]],
      [5,[borderMessage([1,0,0,1],0).subarray(0,-1)]],
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
