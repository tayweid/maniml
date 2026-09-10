/* Serialize renderer changes and draws across the shared canvas. */
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

  render(buffer) {
    const generation = this.generation;
    const length = new DataView(buffer).getUint32(1, true);
    const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 5, length)));
    if (!this.ready || header.renderer !== this.mode) return Promise.resolve(null);
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
