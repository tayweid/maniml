// The bar both rooms share (shell.css, #toolbar): Knuth's and Plass's bar
// in ManimLive. Its menus, the folder in the name pill, and the app's
// update tile live here once, so the landing page and the viewer behave as
// one bar. player.html and the student bundle never load it.
"use strict";

(function () {
  const shell = window.claerbout || null;

  // ---------- the menus ----------
  // Knuth's and Plass's: a click on the tile drops a text menu 10 px under
  // it (shell.css) and puts the focus on its first item (or the current
  // one); the arrows, Home, End and a letter walk it; Escape, Tab, a click
  // elsewhere, a choice or a second click on the tile close it, and the
  // focus goes back where the page says (the viewer's: the stage, which
  // owns the keyboard). While a menu is open it takes every plain key, in
  // the capture phase, so nothing it is given reaches a scene: the
  // viewer's forwarder sends every key it hears to the engine.
  let open = null;            // the entry whose menu is open
  const swallowed = new Set(); // keys taken on the way down, taken on the way up

  function itemsOf(entry) {
    return [...entry.list.querySelectorAll('[role="menuitem"]')]
      .filter((item) => !item.hidden && !item.disabled);
  }

  function closeMenu(focusBack) {
    if (!open) return;
    const entry = open;
    open = null;
    entry.list.hidden = true;
    entry.button.setAttribute("aria-expanded", "false");
    if (focusBack) entry.restore();
  }

  function openMenu(entry) {
    if (open && open !== entry) closeMenu(false);
    open = entry;
    entry.list.hidden = false;
    entry.button.setAttribute("aria-expanded", "true");
    const items = itemsOf(entry);
    const current = items.find((item) => item.getAttribute("aria-current") === "true");
    const first = current || items[0];
    if (first) first.focus({ preventScroll: true });
  }

  function menu(button, list, { restore } = {}) {
    const entry = { button, list, restore: restore || (() => button.focus()) };
    button.addEventListener("click", () => {
      if (open === entry) closeMenu(true);
      else openMenu(entry);
    });
    list.addEventListener("click", (event) => {
      if (open === entry && event.target.closest('[role="menuitem"]')) closeMenu(true);
    });
    return {
      close(focusBack = true) { if (open === entry) closeMenu(focusBack); },
      get isOpen() { return open === entry; },
    };
  }

  document.addEventListener("pointerdown", (event) => {
    if (open && !open.list.contains(event.target) && !open.button.contains(event.target)) {
      closeMenu(false);
    }
  }, true);

  document.addEventListener("keydown", (event) => {
    // A press with no menu open is the page's: if a release of the same
    // key was owed to a menu (its window lost the focus mid-press), the
    // debt is dropped, so this press's release reaches the scene.
    if (!open) { swallowed.delete(event.key); return; }
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const items = itemsOf(open);
    const at = items.indexOf(document.activeElement);
    const go = (index) => {
      if (items.length) items[(index + items.length) % items.length].focus({ preventScroll: true });
    };
    const key = event.key;
    if (key === "Tab") {
      closeMenu(false);
      return;
    }
    event.stopPropagation();
    swallowed.add(key);
    if (key === "Escape") { event.preventDefault(); closeMenu(true); }
    else if (key === "ArrowDown") { event.preventDefault(); go(at + 1); }
    else if (key === "ArrowUp") { event.preventDefault(); go(at < 0 ? -1 : at - 1); }
    else if (key === "Home") { event.preventDefault(); go(0); }
    else if (key === "End") { event.preventDefault(); go(-1); }
    else if (key === "Enter" || key === " ") { /* the focused item's own click */ }
    else if (key.length === 1) {
      event.preventDefault();
      const letter = key.toLowerCase();
      for (let step = 1; step <= items.length; step++) {
        const item = items[(at + step + items.length) % items.length];
        if (item.textContent.trim().toLowerCase().startsWith(letter)) { item.focus(); break; }
      }
    }
    else event.preventDefault();
  }, true);

  document.addEventListener("keyup", (event) => {
    if (swallowed.delete(event.key)) event.stopPropagation();
  }, true);
  window.addEventListener("blur", () => swallowed.clear());

  // ---------- the folder ----------
  /** A folder as a person reads it: their home as ~ (Knuth's tilde()). The
   *  page cannot ask for the home folder, so a home is what macOS and
   *  Linux put there — /Users/<name> or /home/<name> — but not
   *  /Users/Shared, which is no one's. */
  function tilde(path) {
    return path.replace(/^\/(?:Users|home)\/(?!Shared(?:\/|$))[^/]+(?=\/|$)/, "~");
  }

  function dirname(path) {
    const cut = path.lastIndexOf("/");
    return cut > 0 ? path.slice(0, cut) : cut === 0 ? "/" : "";
  }

  /** The file the window holds, told to the shell (its `document`
   *  request): the shell takes it only as an absolute path to an existing
   *  file and answers with what it took, which becomes the window's file —
   *  the one the macOS window menu names and an update's relaunch reopens.
   *  The folder beside the name is the answer's, so it never names a file
   *  the shell refused. In a tab there is no shell to tell, and the folder
   *  is the path's own. Told once per path. A page holding no file (the
   *  landing page) tells null and has no folder to fill. */
  let reported;
  async function setDocument(path, folder) {
    const wanted = typeof path === "string" && path ? path : null;
    if (wanted === reported) return;
    reported = wanted;
    let file = wanted;
    if (shell) {
      try {
        const answer = await shell.request({ type: "document", path: wanted });
        file = answer && typeof answer.path === "string" ? answer.path : null;
      } catch (error) {
        file = null;
      }
      if (wanted !== reported) return;   // a later report has the say
    }
    if (!folder) return;
    const where = file ? dirname(file) : "";
    folder.firstElementChild.textContent = where ? tilde(where) : "";
    folder.title = where;
    folder.hidden = !where;
  }

  // ---------- the update ----------
  /** ManimLive.app updating itself (the shell's update.js; also ManimLive
   *  menu → Check for Updates…). The shell looks at its site after launch
   *  and tells every page of a newer build, and tells each page again as
   *  it loads: the tile appears. A click has the shell download that
   *  build, swap it in and relaunch, the windows reopening on their
   *  scenes; the steps show on the tile, and a failure goes to `failed`
   *  as well. Nothing shows in a tab. */
  function updates(button, { failed } = {}) {
    if (!shell || !button) return;
    const label = button.querySelector(".control-label");
    const show = (text, enabled, title) => {
      button.hidden = false;
      button.disabled = !enabled;
      if (label) label.textContent = text;
      if (title) button.title = title;
    };
    shell.on("update", (step) => {
      if (!step) return;
      const when = step.latest && step.latest.built ? " (built " + step.latest.built.slice(0, 10) + ")" : "";
      switch (step.state) {
        case "available":
          show("Update", true, "A new ManimLive is available" + when + " — install it and relaunch");
          break;
        case "downloading":
        case "unpacking":
        case "completing":
        case "installing":
          show("Updating…", false, step.text || "Updating ManimLive…");
          break;
        case "ready":
          show("Relaunching…", false, step.text || "ManimLive relaunches now");
          break;
        case "failed":
          show("Update", true, "Install the new ManimLive and relaunch");
          if (failed) failed("Could not update ManimLive: " + (step.text || "unknown error"));
          break;
        default:
          break;
      }
    });
    button.addEventListener("click", () => {
      show("Updating…", false, "Updating ManimLive…");
      shell.request({ type: "update", action: "install" });
    });
  }

  window.ManimlBar = { menu, tilde, dirname, setDocument, updates };
})();
