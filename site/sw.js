// Kill switch, not a service worker.
//
// The hosted build used to be an installable PWA whose worker cached the app
// shell. Deleting that file is not enough: a browser that installed the old
// worker keeps running it, and would go on serving a cached shell that tries
// to pair with a local engine over a protocol that no longer exists. So this
// file has to keep existing at the same URL, and its only job is to remove
// its predecessor.
//
// It registers no fetch handler, so it never serves anything.
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) await caches.delete(key);
    await self.registration.unregister();
    // Reload any window still running under the old worker so it lands on the
    // current page rather than whatever the dead cache last held.
    for (const client of await self.clients.matchAll({ type: "window" })) {
      client.navigate(client.url);
    }
  })());
});
