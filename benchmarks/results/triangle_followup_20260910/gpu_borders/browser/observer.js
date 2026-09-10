window.qa={errors:[],cacheMisses:0,frames:0,adapters:[],cases:[]};
window.addEventListener('unhandledrejection',e=>qa.errors.push('Unhandled: '+String(e.reason)));
const originalAdapter=navigator.gpu?.requestAdapter.bind(navigator.gpu);
if(originalAdapter)navigator.gpu.requestAdapter=async(...args)=>{
 const adapter=await originalAdapter(...args); if(!adapter)return adapter;
 qa.adapters.push({...adapter.info});
 const requestDevice=adapter.requestDevice.bind(adapter);
 adapter.requestDevice=async(...args)=>{const device=await requestDevice(...args);qa.device=device;
  device.addEventListener('uncapturederror',e=>qa.errors.push(e.error.message));return device;};return adapter;
};
const originalConfigure=globalThis.GPUCanvasContext?.prototype.configure;
if(originalConfigure)GPUCanvasContext.prototype.configure=function(options){
 qa.context=this;qa.device=options.device;qa.format=options.format;
 return originalConfigure.call(this,{...options,usage:(options.usage||GPUTextureUsage.RENDER_ATTACHMENT)|GPUTextureUsage.COPY_SRC});
};
function assert(test,message){if(!test)throw new Error(message);}
function header(buffer){const n=new DataView(buffer).getUint32(1,true);return JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,5,n)));}
async function pixels(canvas){
 const width=canvas.width,height=canvas.height,row=Math.ceil(width*4/256)*256,device=qa.device;
 const buffer=device.createBuffer({size:row*height,usage:GPUBufferUsage.COPY_DST|GPUBufferUsage.MAP_READ});
 const encoder=device.createCommandEncoder();
 encoder.copyTextureToBuffer({texture:qa.context.getCurrentTexture()},{buffer,bytesPerRow:row,rowsPerImage:height},{width,height});
 device.queue.submit([encoder.finish()]);await buffer.mapAsync(GPUMapMode.READ);
 const raw=new Uint8Array(buffer.getMappedRange()),result=new Uint8Array(width*height*4);
 for(let y=0;y<height;y++)result.set(raw.subarray(y*row,y*row+width*4),y*width*4);
 buffer.unmap();buffer.destroy();
 if(qa.format.startsWith('bgra'))for(let i=0;i<result.length;i+=4)[result[i],result[i+2]]=[result[i+2],result[i]];
 return result;
}
function center(bytes,canvas){return Array.from(bytes.slice((Math.floor(canvas.height/2)*canvas.width+Math.floor(canvas.width/2))*4,(Math.floor(canvas.height/2)*canvas.width+Math.floor(canvas.width/2))*4+4));}
function delta(a,b){assert(a.length===b.length,'pixel dimensions differ');let count=0,max=0,sum=0;for(let i=0;i<a.length;i++){const d=Math.abs(a[i]-b[i]);if(d)count++;max=Math.max(max,d);sum+=d;}return{changedChannels:count,max,mae:sum/a.length};}
async function finish(result){
 const safe={...result,errors:qa.errors,cacheMisses:qa.cacheMisses,adapters:qa.adapters};
 window.qaResult=safe;document.getElementById('report').textContent=JSON.stringify(safe,null,2);
 await fetch('/report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(safe)});
}
