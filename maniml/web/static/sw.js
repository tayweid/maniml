// The installed app's shell.
//
// This exists so ManimLive opens when you click its icon even if the engine
// is not running: the window appears, says the engine is not there, and heals
// itself the moment you start it, because the page reconnects on its own.
//
// Network-first, always. The engine serves this file, so the network is a
// local process — fast, and authoritative about its own assets. The cache is
// only the fallback for when it is not running.
//
// VERSION is replaced by the installed package version when the engine serves
// this file (web/assets.py). That matters twice: the bytes change on upgrade,
// which is what makes the browser install the new worker at all, and the
// cache name changes with it, so an upgraded engine can never be handed a
// shell cached by the old one.
const VERSION = "__MANIML_VERSION__";
const CACHE = `maniml-shell-${VERSION}`;
const SHELL = ["/", "/app.html", "/viewer.html", "/shell.css"];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(SHELL).catch(() => {});
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key !== CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) {
    return;
  }
  event.respondWith((async () => {
    try {
      const response = await fetch(request);
      if (response.ok && request.mode === "navigate") {
        const cache = await caches.open(CACHE);
        await cache.put(request, response.clone());
      }
      return response;
    } catch (error) {
      // The engine is not running. Serve the shell so the window still opens.
      const cached = await caches.match(request)
        || await caches.match("/app.html");
      if (cached) return cached;
      throw error;
    }
  })());
});
