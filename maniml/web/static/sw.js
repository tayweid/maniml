// Kill switch, not a service worker.
//
// Until 2026-10-01 the engine served a manifest and a caching worker here,
// which made http://localhost:8685 an installable app: its own icon, a
// window without a tab strip, a shell that opened when the engine was not
// running. ManimLive.app on the Claerbout shell is the installed app now,
// with a window, an icon, a port and an engine lifetime of its own, so the
// manifest and the install offer are gone. Deleting this file is not
// enough: a browser that installed the old worker keeps running it, and
// would go on serving its cached shell against an engine whose page has
// moved on. So this file has to keep existing at the same URL, and its
// only job is to remove its predecessor.
//
// It registers no fetch handler, so it never serves anything.
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) await caches.delete(key);
    await self.registration.unregister();
    // Reload any window still running under the old worker so it lands on the
    // engine's current page rather than whatever the dead cache last held.
    for (const client of await self.clients.matchAll({ type: "window" })) {
      client.navigate(client.url);
    }
  })());
});
