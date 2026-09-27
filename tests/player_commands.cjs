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
// Format 7 Phase B batches, synthetic like the paint and border messages: a
// patch run over one four-curve object, a one-patch net, and a blend program
// drawn three ways (a stroke, a patch run, a net). The variant picks the
// content hashes and a marker word in every definition, so a seek can be
// checked to restore the right one; `marker` alone changes the bytes under
// the same hashes, which a recording may not do.
function phaseBMessage(variant, frameId, {cached=false, definition=true, empty=false, format=7, marker, mutate=()=>{}}={}) {
  const v=variant==='a'?1:2, word=marker??v, hash=prefix=>(prefix+v).repeat(16);
  const header={renderer:'triangles',format_version:format,test_frame:frameId,camera:{},background:[0,0,0,1],
    resolution:[32,16],samples:4,supersample:2,batches:[],paint_data:{},border_data:{},object_data:{},net_data:{},
    program_data:{},texture_data:{}};
  let raw=Buffer.alloc(0);
  const define=(table,key,data)=>{header[table][key]={offset:raw.length,nbytes:data.length}; raw=Buffer.concat([raw,data]);};
  const floats=(count,value)=>{const data=Buffer.alloc(count*4); data.writeFloatLE(value,0); return data;};
  // An object record: base point, curve offset 0, curve count, bordered, sign 0.
  const objects=curves=>{const data=floats(8,word); data.writeFloatLE(curves,16); data.writeFloatLE(1,20); return data;};
  const border=curves=>{const data=Buffer.alloc(176*curves);
    for(let c=0;c<curves;c++){data.writeFloatLE(1,(c*44+37)*4); data.writeFloatLE(word,(c*44+40)*4);} return data;};
  if(!empty) {
    const capacity=8, strip=6*(capacity/2-1);
    const base={kind:'generated',stride:40,uniforms:{},instances:1,indexed:false,index_count:0,fill_num_verts:0};
    const program={kind:'blend',sources:[hash('f'),hash('0')],scalars:[frameId/10],rows:5,channels:17};
    const netProgram={kind:'blend',sources:[hash('5'),hash('6')],scalars:[frameId/10],rows:9,channels:10};
    header.batches=[
      {...base,pipeline:'patch',hash:hash('a'),num_verts:capacity*4,count:4*(6+strip),
       border:{hash:hash('b'),num_curves:4,capacity},objects:{hash:hash('c'),count:1}},
      {...base,pipeline:'surface',hash:hash('d'),num_verts:9,count:24,net:{hash:hash('e'),nu:3,nv:3,channels:10,capacity:2,density:0}},
      {...base,pipeline:'stroke',stride:68,hash:hash('1'),num_verts:6,instances:2,count:4,program},
      {...base,pipeline:'patch',hash:hash('2'),num_verts:capacity*2,count:2*(6+strip),program,
       border:{hash:hash('3'),num_curves:2,capacity},objects:{hash:hash('4'),count:1}},
      {...base,pipeline:'surface',hash:hash('7'),num_verts:9,count:24,program:netProgram,
       net:{hash:hash('8'),nu:3,nv:3,channels:10,capacity:2,density:0}},
    ];
    for(const batch of header.batches) {
      if(cached) batch.cached=true;
      else {batch.offset=raw.length; if(batch.border) batch.border.layout=[[batch.border.num_curves,1,0]];}
    }
    if(definition) {
      define('border_data',hash('b'),border(4)); define('object_data',hash('c'),objects(4));
      define('net_data',hash('e'),floats(90,word));
      define('program_data',hash('f'),floats(85,word)); define('program_data',hash('0'),floats(85,word+10));
      define('object_data',hash('4'),objects(2));
      define('program_data',hash('5'),floats(90,word)); define('program_data',hash('6'),floats(90,word+10));
    }
  }
  mutate(header);
  const encoded=Buffer.from(JSON.stringify(header)), output=Buffer.alloc(5+encoded.length);
  output[0]=3; output.writeUInt32LE(encoded.length,1); encoded.copy(output,5);
  return Buffer.concat([output,raw]);
}
// The definitions a Phase B frame's batches reference, in batch order, each
// as [table, marker word]; asserts every one is in the frame with its span.
function phaseBRecords(header, frame, length) {
  const payload=frame.byteLength-5-length;
  const span=(table,hash,label)=>{
    const info=header[table]?.[hash];
    assert.ok(info,`every requested frame must carry its own ${label}`);
    assert.ok(Number.isInteger(info.offset)&&info.offset>=0&&info.offset+info.nbytes<=payload,`${label} span within the payload`);
    return new DataView(frame,5+length+info.offset,info.nbytes);
  };
  return header.batches.flatMap(batch=>{
    const found=[], patch=batch.pipeline==='patch'||batch.pipeline==='patch_depth';
    if(batch.program) for(const hash of batch.program.sources) {
      const rows=span('program_data',hash,'program source');
      assert.equal(rows.byteLength,batch.program.rows*batch.program.channels*4);
      found.push(['rows',rows.getFloat32(0,true)]);
    }
    if(patch) {
      const table=span('object_data',batch.objects.hash,'object table');
      assert.equal(table.byteLength,32*batch.border.layout.length,'a rehydrated patch run carries its layout');
      found.push(['objects',table.getFloat32(0,true)]);
      if(!batch.program) {
        const curves=span('border_data',batch.border.hash,'border definition');
        assert.equal(curves.byteLength,176*batch.border.num_curves);
        found.push(['border',curves.getFloat32(40*4,true)]);
      }
    }
    if(batch.net&&!batch.program) {
      const net=span('net_data',batch.net.hash,'net');
      assert.equal(net.byteLength,batch.net.nu*batch.net.nv*batch.net.channels*4);
      found.push(['net',net.getFloat32(0,true)]);
    }
    return found;
  });
}
async function run(format, messages, transformMeta=x=>x) {
  const elements=new Map(), listeners=new Map(), rendered=[], initialized=[], frameIds=[], paintColors=[], borderColors=[], records=[];
  // The player reports a failed frame in its status and carries on, so a
  // definition check that fails mid-sequence is kept here as well.
  const failures=[];
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
    try {
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
        // A patch run's border is its curve records; phaseBRecords checks it.
        if(!batch.border||batch.pipeline==='patch'||batch.pipeline==='patch_depth') return [];
        const info=header.border_data?.[batch.border.hash];
        assert.ok(info,'every requested frame must carry its own border definition');
        assert.equal(batch.index_offset-batch.offset,batch.fill_num_verts*40);
        // A format 6/7 run reserves its own capacity; format 5 always reserved 64.
        assert.equal(batch.num_verts,batch.fill_num_verts+(batch.border.capacity??64)*batch.border.num_curves);
        const values=new DataView(frame,5+length+info.offset,info.nbytes);
        return [Array.from({length:4},(_,i)=>values.getFloat32((40+i)*4,true))];
      }));
      records.push(phaseBRecords(header,frame,length));
    } catch(error) { failures.push(error); throw error; }
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
  return {elements,listeners,rendered,initialized,frameIds,paintColors,borderColors,records,failures,fail(){failNext=true;},tick:()=>interval()};
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
    for(const [format,renderer,expected] of [[1,null,'winding'],[2,'triangles','triangles'],[2,'winding','winding'],[3,'triangles','triangles'],[3,'winding','winding'],[4,'triangles','triangles'],[4,'winding','winding'],[5,'triangles','triangles'],[5,'winding','winding'],[6,'triangles','triangles'],[6,'winding','winding'],[7,'triangles','triangles'],[7,'winding','winding'],[8,'triangles','triangles']]) {
      const page=await run(format,[message(renderer)]);
      assert.deepEqual(page.initialized,[expected]);
      assert.deepEqual(page.rendered,[expected]);
    }
    const future=await run(9,[message('triangles')]);
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
  } else if(mode==='phaseB') {
    // Definitions in frame 0 and frame 3, referenced by the cached frames after
    // each; a forward tick, a segment jump and reverse seeks must all restore
    // the definitions of the frame shown, never the last ones sent.
    const expected=v=>[['objects',v],['border',v],['net',v],['rows',v],['rows',v+10],
      ['rows',v],['rows',v+10],['objects',v],['rows',v],['rows',v+10]];
    const page=await run(7,[phaseBMessage('a',0),phaseBMessage('a',1,{cached:true,definition:false}),
      phaseBMessage('a',2,{empty:true}),phaseBMessage('b',3),phaseBMessage('b',4,{cached:true,definition:false})],
      meta=>({...meta,segments:3,lines:[1,2,3],frames:meta.frames.map((frame,i)=>({...frame,segment:[0,0,1,2,2][i]}))}));
    assert.deepEqual(page.records,[expected(1)]);
    page.elements.get('playbtn').onclick(); await page.tick();
    assert.deepEqual(page.frameIds.at(-1),1); assert.deepEqual(page.records.at(-1),expected(1));
    page.elements.get('chips').children[2].onclick();
    await new Promise(resolve=>setImmediate(resolve));
    assert.deepEqual(page.frameIds.at(-1),3); assert.deepEqual(page.records.at(-1),expected(2));
    await page.tick(); assert.deepEqual(page.frameIds.at(-1),4); assert.deepEqual(page.records.at(-1),expected(2));
    const seek=()=>page.listeners.get('keydown')({key:'ArrowLeft',shiftKey:true,preventDefault(){}});
    await seek(); assert.deepEqual(page.records.at(-1),[]);
    await seek(); assert.deepEqual(page.frameIds.at(-1),1); assert.deepEqual(page.records.at(-1),expected(1));
    const unhandled=[];
    process.on('unhandledRejection',error=>unhandled.push(error));
    page.fail(); await seek();
    assert.match(page.elements.get('status').textContent,/Playback error/);
    await seek(); assert.deepEqual(page.records.at(-1),expected(1));
    assert.equal(page.elements.get('status').textContent,'WebGPU');
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(unhandled.length,0);
    assert.deepEqual(page.failures,[]);
  } else if(mode==='export') {
    // A real export folder (tests.test_export): the player's own load path
    // over scene.json and scene.bin.gz, every frame forward, every frame
    // back through the segment rewinds, then segment jumps.
    const zlib=require('node:zlib'), dir=process.argv[3];
    const meta=JSON.parse(fs.readFileSync(path.join(dir,'scene.json'),'utf8'));
    const data=zlib.gunzipSync(fs.readFileSync(path.join(dir,'scene.bin.gz')));
    const messages=[]; let offset=0;
    for(const frame of meta.frames) {messages.push(data.subarray(offset,offset+frame.len)); offset+=frame.len;}
    const page=await run(meta.format_version,messages,()=>meta);
    assert.deepEqual(page.initialized,['triangles']);
    page.elements.get('playbtn').onclick();
    for(let i=1;i<messages.length;i++) await page.tick();
    const key=(name,shiftKey=false)=>page.listeners.get('keydown')({key:name,shiftKey,preventDefault(){}});
    for(let segment=0;segment<meta.segments;segment++) {
      await key('ArrowLeft');
      for(let i=0;i<messages.length;i++) await page.tick();
    }
    await key('ArrowLeft',true);
    for(const chip of [...page.elements.get('chips').children].reverse()) {
      chip.onclick(); await new Promise(resolve=>setImmediate(resolve));
    }
    assert.deepEqual(page.failures,[]);
    assert.equal(page.elements.get('status').textContent,'WebGPU');
    assert.ok(page.rendered.length>=2*messages.length,'every frame drew forward and back');
    const tags={};
    for(const [tag] of page.records.flat()) tags[tag]=(tags[tag]??0)+1;
    process.stdout.write(JSON.stringify({frames:messages.length,rendered:page.rendered.length,tags}));
  } else if(mode==='corrupt') {
    const missing=table=>({mutate:header=>{delete header[table][Object.keys(header[table])[0]];}});
    const cases=[
      [3,[message('triangles').subarray(0,-1)]],
      [3,[message('unknown')]], [3,[message(null)]],
      [3,[message('triangles'),message('winding')]],
      [3,[message('triangles')],meta=>({...meta,frames:[{len:1,segment:0}]})],
      [4,[paintMessage([1,0,0,1],0,{definition:false})]],
      [4,[paintMessage([1,0,0,1],0).subarray(0,-1)]],
      [5,[borderMessage([1,0,0,1],0,{definition:false})]],
      [5,[borderMessage([1,0,0,1],0).subarray(0,-1)]],
      [7,[phaseBMessage('a',0,{definition:false})]],
      [7,[phaseBMessage('a',0,missing('object_data'))]],
      [7,[phaseBMessage('a',0,missing('net_data'))]],
      [7,[phaseBMessage('a',0,missing('program_data'))]],
      [7,[phaseBMessage('a',0,missing('border_data'))]],
      [7,[phaseBMessage('a',0),phaseBMessage('a',1,{marker:5})]],
      [7,[phaseBMessage('a',0,{cached:true,definition:false})]],
      [7,[phaseBMessage('a',0).subarray(0,-1)]],
      [6,[phaseBMessage('a',0,{format:6})]],
      [7,[phaseBMessage('a',0,{mutate:header=>{header.batches[0].objects.count=2;}})]],
      [7,[phaseBMessage('a',0,{mutate:header=>{header.batches[1].net.nu=4;}})]],
      [7,[phaseBMessage('a',0,{mutate:header=>{header.batches[2].program.rows=7;}})]],
      [7,[phaseBMessage('a',0,{mutate:header=>{header.batches[3].border.num_curves=3;}})]],
      [7,[phaseBMessage('a',0,{mutate:header=>{header.batches[4].program.channels=17;}})]],
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
