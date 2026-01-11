// Service worker for offline support and background sync
const CACHE_NAME = "door-assistant-v1";

const urlsToCache = [
  "/",
  "/static/index.html"
];

self.addEventListener("install", (evt) => {
  evt.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(urlsToCache);
    })
  );
});

self.addEventListener("activate", (evt) => {
  evt.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});

self.addEventListener("fetch", (evt) => {
  // Network first for API calls, fallback to cache
  if (evt.request.url.includes("/events/") || evt.request.method === "POST") {
    evt.respondWith(
      fetch(evt.request).catch(() => {
        return caches.match(evt.request);
      })
    );
  } else {
    // Cache first for static assets
    evt.respondWith(
      caches.match(evt.request).then((response) => {
        return response || fetch(evt.request);
      })
    );
  }
});
