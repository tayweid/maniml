const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');
global.window = {};
vm.runInThisContext(fs.readFileSync(path.join(__dirname, '../maniml/web/static/renderer_selection.js'), 'utf8'));
const Selection = window.ManimlRendererSelection;
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve=a; reject=b;}); return {promise,resolve,reject}; };
function payload(mode) {
  const header = Buffer.from(JSON.stringify({renderer:mode, unsupported:[]}));
  const data = Buffer.alloc(5+header.length);
  data[0] = 3; data.writeUInt32LE(header.length,1); header.copy(data,5);
  return data.buffer.slice(data.byteOffset, data.byteOffset+data.byteLength);
}
function fixture() {
  const calls = [];
  const driver = name => ({
    init: async () => { calls.push(`init:${name}`); },
    destroy: async () => { calls.push(`destroy:${name}`); },
    render: async () => { calls.push(`render:${name}`); return {renderer:name, unsupported:[]}; },
  });
  const drivers = {triangles:driver('triangles'), winding:driver('winding')};
  return {calls,drivers,selection:new Selection({},drivers)};
}
(async () => {
  const {calls,drivers,selection} = fixture();
  assert.equal(selection.mode,'triangles');
  await selection.select('triangles');
  await selection.render(payload('triangles'));
  assert.equal(await selection.render(payload('winding')),null);
  const held = deferred();
  drivers.triangles.render = async () => { calls.push('render:held'); await held.promise; calls.push('render:done'); return {}; };
  const rendering = selection.render(payload('triangles'));
  await Promise.resolve();
  const stale = selection.render(payload('triangles'));
  const switching = selection.select('winding');
  await Promise.resolve();
  assert(!calls.includes('destroy:triangles'));
  held.resolve();
  assert.equal(await rendering,null);
  assert.equal(await stale,null);
  await switching;
  assert(calls.indexOf('render:done') < calls.indexOf('destroy:triangles'));
  assert(calls.indexOf('destroy:triangles') < calls.indexOf('init:winding'));
  await selection.render(payload('winding'));
  await selection.select('triangles');
  assert.equal(calls.filter(x=>x==='init:triangles').length,2);
  assert(calls.includes('destroy:winding'));
  assert.equal(calls.filter(x=>x==='render:held').length,1);
  await assert.rejects(selection.select('__proto__'));
  assert.equal(selection.mode,'triangles');

  const rapid = fixture();
  const initializing = deferred();
  rapid.drivers.triangles.init = async () => { rapid.calls.push('init:held'); await initializing.promise; };
  const first = rapid.selection.select('triangles');
  await Promise.resolve();
  const second = rapid.selection.select('winding');
  initializing.resolve();
  assert.equal(await first,false);
  await second;
  assert.deepEqual(rapid.calls,['init:held','destroy:triangles','init:winding']);

  const failure = fixture();
  failure.drivers.triangles.init = async () => { throw new Error('no GPU'); };
  await assert.rejects(failure.selection.select('triangles'), /no GPU/);
  assert(!failure.selection.ready);
  await failure.selection.select('winding');
  assert.deepEqual(failure.calls,['destroy:triangles','init:winding']);
})().catch(error => { console.error(error); process.exitCode=1; });
