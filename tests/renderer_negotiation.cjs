// Execute the shipped viewer's negotiation handlers with real selection
// lifecycle code and fake sockets/drivers. No DOM layout or GPU is needed.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.join(__dirname, "..", "maniml", "web", "static");
const page = fs.readFileSync(path.join(root, "viewer.html"), "utf8");
function section(start, end) {
  const first = page.indexOf(start);
  const last = page.indexOf(end, first);
  assert.ok(first >= 0 && last > first, `missing shipped handler: ${start}`);
  return page.slice(first, last);
}
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

function fixture(origin) {
  const elements = new Map(), calls = [], sockets = [];
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      disabled: true, value: "triangles", classList: { add() {}, remove() {}, toggle() {} },
      focus() {},
    });
    return elements.get(id);
  }
  class Socket {
    static OPEN = 1;
    constructor() { this.readyState = 1; this.sent = []; sockets.push(this); }
    send(text) { this.sent.push(JSON.parse(text)); }
    emit(message) { this.onmessage({ data: JSON.stringify(message) }); }
    close() { this.readyState = 3; this.onclose(); }
  }
  const driver = name => ({
    init: async () => { calls.push(`init:${name}`); },
    destroy: async () => { calls.push(`destroy:${name}`); },
    render: async () => ({}),
  });
  const drivers = { triangles: driver("triangles"), winding: driver("winding") };
  const context = vm.createContext({
    window: {}, WebSocket: Socket, canvas: element("view"),
    document: { getElementById: element, body: element("body") },
    ManimlWGPU: drivers.triangles, ManimlWindingWGPU: drivers.winding,
    crypto: { randomUUID: () => origin }, wsUrl: "ws://fixture/",
    clearTimeout() {}, scheduleReconnect() {}, hideConnectionIssue() {},
    applyCapabilities() {}, appendLog() {}, setRenderError() {},
    presenter: { stateChanged() {} }, applyEnv() {},
    stageSource: "live", autoPlaybackSuppressed: false, geometryQueue: [],
    lastLiveState: null, location: { reload() { throw Error("unexpected reload"); } },
    exitPlayback() { context.stageSource = "live"; },
    console,
  });
  vm.runInContext(fs.readFileSync(path.join(root, "renderer_selection.js"), "utf8"), context);
  vm.runInContext("const ManimlRendererSelection = window.ManimlRendererSelection;", context);
  vm.runInContext(section("let ws = null;", "const OVERLAY_AFTER_RECONNECTS"), context);
  vm.runInContext(section("function send(obj)", "function applyCapabilities"), context);
  vm.runInContext(section('const glWarn = document.getElementById("glwarn");', "function setRenderError"), context);
  vm.runInContext(section("function handleMessage(data)", "// Scene picker:"), context);
  vm.runInContext(section("function connect(manualRetry = false)", 'document.getElementById("retry-connection")'), context);
  return {
    calls, drivers, sockets, element,
    socket: () => sockets.at(-1),
    run: code => vm.runInContext(code, context),
    ready() { this.socket().emit({ type: "ready", boot: "same-engine", capabilities: [] }); },
    state(renderer) { this.socket().emit({ type: "state", renderer, current: 0, present: false }); },
    choose(renderer) { element("renderer-select").value = renderer; element("renderer-select").onchange(); },
  };
}

(async () => {
  const reload = fixture("reload");
  reload.ready();
  await flush();
  assert.deepEqual(reload.calls, [], "ready must await authoritative state before initializing");
  assert.deepEqual(reload.socket().sent, [], "ready must not select the page default");
  assert.ok(reload.element("renderer-select").disabled);
  reload.state("winding");
  await flush();
  assert.deepEqual(reload.calls, ["init:winding"]);
  assert.equal(reload.element("renderer-select").value, "winding");
  assert.ok(!reload.element("renderer-select").disabled);
  assert.ok(reload.socket().sent.some(event => event.type === "mode" && event.geometry));
  assert.ok(reload.socket().sent.every(event => !Object.hasOwn(event, "renderer")));

  const oldSocket = reload.socket();
  oldSocket.close();
  reload.run("connect(); sendRendererMode();");
  reload.ready();
  oldSocket.emit({ type: "renderer", renderer: "triangles", origin: "another-tab" });
  oldSocket.close();
  await flush();
  assert.equal(reload.element("renderer-select").value, "winding");
  assert.deepEqual(reload.socket().sent, []);
  reload.state("triangles");
  await flush();
  assert.equal(reload.element("renderer-select").value, "triangles");
  assert.deepEqual(reload.calls, ["init:winding", "destroy:winding", "init:triangles"]);
  assert.ok(reload.socket().sent.every(event => !Object.hasOwn(event, "renderer")));

  const pending = fixture("pending");
  const held = deferred();
  pending.drivers.winding.init = async () => { pending.calls.push("init:held"); await held.promise; };
  pending.ready(); pending.state("winding");
  await flush();
  pending.socket().close();
  pending.run("connect();"); pending.ready();
  held.resolve();
  await flush();
  assert.deepEqual(pending.socket().sent, [], "old initialization cannot announce into a new handshake");
  pending.state("triangles");
  await flush();
  assert.equal(pending.element("renderer-select").value, "triangles");
  assert.ok(pending.socket().sent.every(event => !Object.hasOwn(event, "renderer")));

  const sameMode = fixture("same-mode"), sameInit = deferred();
  sameMode.drivers.winding.init = () => sameInit.promise;
  sameMode.ready(); sameMode.state("winding");
  await flush();
  sameMode.socket().close(); sameMode.run("connect();");
  sameMode.ready(); sameMode.state("winding");
  sameInit.resolve();
  await flush();
  assert.equal(sameMode.socket().sent.filter(event => event.type === "mode").length, 1,
    "reconnect can await the existing initialization and announce exactly once");

  const first = fixture("first"), second = fixture("second");
  for (const tab of [first, second]) { tab.ready(); tab.state("winding"); }
  await flush();
  first.choose("triangles"); first.choose("winding");
  const requests = first.socket().sent.filter(event => Object.hasOwn(event, "renderer"));
  assert.deepEqual(requests.map(event => event.renderer), ["triangles", "winding"]);
  for (const request of requests) {
    for (const tab of [first, second]) {
      tab.socket().emit({ type: "renderer", renderer: request.renderer,
        origin: request.renderer_origin, request: request.renderer_request });
      tab.state(request.renderer);
    }
  }
  await flush();
  for (const tab of [first, second]) assert.equal(tab.element("renderer-select").value, "winding");
  assert.equal(first.socket().sent.filter(event => Object.hasOwn(event, "renderer")).length, 2);
  assert.ok(second.socket().sent.every(event => !Object.hasOwn(event, "renderer")),
    "following another tab must not issue another selection");

  const concurrentA = fixture("concurrent-a"), concurrentB = fixture("concurrent-b");
  for (const tab of [concurrentA, concurrentB]) { tab.ready(); tab.state("winding"); }
  await flush();
  concurrentB.choose("triangles"); concurrentB.choose("winding");
  concurrentA.choose("triangles");
  const selections = tab => tab.socket().sent.filter(event => Object.hasOwn(event, "renderer"));
  async function acknowledge(request) {
    for (const tab of [concurrentA, concurrentB]) {
      tab.socket().emit({ type: "renderer", renderer: request.renderer,
        origin: request.renderer_origin, request: request.renderer_request });
      tab.state(request.renderer);
    }
    await flush();
  }
  // The server receives B's two requests before A's one. The second remote
  // event changes A's optimistic mode; A must then accept its final own ack.
  for (const request of selections(concurrentB)) await acknowledge(request);
  assert.equal(concurrentA.element("renderer-select").value, "winding");
  await acknowledge(selections(concurrentA)[0]);
  for (const tab of [concurrentA, concurrentB]) {
    assert.equal(tab.element("renderer-select").value, "triangles",
      "both tabs must converge on the server's last processed selection");
  }
  assert.equal(selections(concurrentA).length, 1);
  assert.equal(selections(concurrentB).length, 2);

  // Same-mode explicit selections still receive a request id. Once accepted,
  // a duplicate own ack must not undo a later remote selection.
  concurrentA.choose("triangles");
  const sameRequest = selections(concurrentA).at(-1);
  assert.ok(sameRequest.renderer_request > selections(concurrentA)[0].renderer_request);
  await acknowledge(sameRequest);
  concurrentA.socket().emit({ type: "renderer", renderer: "winding", origin: "remote" });
  concurrentA.socket().emit({ type: "renderer", renderer: "triangles",
    origin: sameRequest.renderer_origin, request: sameRequest.renderer_request });
  await flush();
  assert.equal(concurrentA.element("renderer-select").value, "winding");
})().catch(error => { console.error(error); process.exitCode = 1; });
