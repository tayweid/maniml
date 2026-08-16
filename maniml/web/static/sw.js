"use strict";

// Network-first keeps the hosted UI moving quickly while retaining a small,
// non-sensitive offline shell. Local HTTP APIs and WebSockets are on other
// origins and are deliberately never cached here.
const CACHE_NAME = "maniml-app-shell-v2";
const APP_SHELL = [
  "./",
  "./index.html",
  "./app.html",
  "./viewer.html",
  "./manifest.webmanifest",
  "./gl.js",
  "./webgpu.js",
  "./icons/maniml-192.png",
  "./icons/maniml-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(
        names
          .filter((name) => name.startsWith("maniml-app-shell-")
            && name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(async () => {
        const cached = await caches.match(event.request);
        if (cached) return cached;
        if (event.request.mode === "navigate") {
          return caches.match("./app.html");
        }
        throw new Error("offline and resource is not cached");
      })
  );
});
