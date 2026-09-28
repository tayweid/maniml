/* Serialize renderer changes and draws across the shared canvas. */
// A header whose renderer follows only integer fields, and that renderer.
const RENDERER_FIRST = /^\{\s*(?:"[a-z_]+"\s*:\s*-?\d+\s*,\s*)*"renderer"\s*:\s*"([a-z0-9_]*)"/;
// The renderer a mode's frames name where it is not the mode's own. Phase
// A's frames are the bytes Phase A has always written, "triangles" (the
// default's name), which the engine's golden pin holds and every recording
// names; so a frame of the default still in flight across a switch to
// Phase A, or back, is drawn once before the switch's full frame replaces
// it, and the default differs from Phase A only by flips gated on pixels.
const FRAMES_OF = { phase_a: "triangles" };
window.ManimlRendererSelection = class {
  constructor(canvas, drivers) {
    this.canvas = canvas;
    this.drivers = drivers;
    this.mode = "triangles";
    this.ready = false;
    this.generation = 0;
    this.active = null;
    this.pending = null;
    this.chain = Promise.resolve();
  }

  select(mode) {
    if (!Object.hasOwn(this.drivers, mode)) return Promise.reject(new Error("Unknown renderer"));
    if (mode === this.mode && this.pending) return this.pending;
    if (mode === this.mode && this.ready) return Promise.resolve(true);
    this.mode = mode;
    this.ready = false;
    const generation = ++this.generation;
    const work = this.chain.then(async () => {
      if (generation !== this.generation) return false;
      if (this.active) {
        await this.active.destroy();
        this.active = null;
      }
      const driver = this.drivers[mode];
      // Record the driver before init so a failed or superseded init is
      // still released before another driver configures this canvas.
      this.active = driver;
      await driver.init(this.canvas);
      if (generation !== this.generation) return false;
      this.ready = true;
      return true;
    });
    this.chain = work.catch(() => {});
    this.pending = work;
    const clear = () => { if (this.pending === work) this.pending = null; };
    work.then(clear, clear);
    return work;
  }

  invalidate() {
    // Keep the active driver, but prevent queued old frames from replacing
    // the explicit error for a rejected scene snapshot.
    this.generation += 1;
  }

  // The renderer a message was made for, read from the start of its header
  // without parsing the rest: the engine writes the renderer after nothing
  // but integer fields (format 7's version; format 8's version, epoch,
  // frame and base), and the driver parses the header anyway, so a second
  // whole parse here would be most of the page's work on a delta or a
  // resend. A header laid out otherwise is parsed.
  rendererOf(buffer) {
    const length = new DataView(buffer).getUint32(1, true);
    const decoder = new TextDecoder();
    const head = RENDERER_FIRST.exec(decoder.decode(new Uint8Array(buffer, 5, Math.min(length, 256))));
    if (head) return head[1];
    return JSON.parse(decoder.decode(new Uint8Array(buffer, 5, length))).renderer;
  }

  render(buffer) {
    const generation = this.generation;
    const renderer = this.rendererOf(buffer);
    if (!this.ready || renderer !== (FRAMES_OF[this.mode] ?? this.mode)) return Promise.resolve(null);
    const work = this.chain.then(async () => {
      // A switch invalidates queued old frames; the active draw finishes
      // before select() destroys its resources or reconfigures the canvas.
      if (!this.ready || generation !== this.generation) return null;
      const result = await this.active.render(buffer);
      return generation === this.generation ? result : null;
    });
    this.chain = work.catch(() => {});
    return work;
  }
};
