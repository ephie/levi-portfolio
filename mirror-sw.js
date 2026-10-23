const originalOrigin = "https://goldschmidt-levi.base44.app";

self.addEventListener("install", event => event.waitUntil(self.skipWaiting()));
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (url.origin === self.location.origin &&
      (url.pathname === "/__mirror__" || url.pathname === "/mirror-sw.js")) {
    return;
  }
  if (!["http:", "https:"].includes(url.protocol)) return;
  if (event.request.method !== "GET") {
    // Recorded public data is read-only; never submit analytics or mutations.
    event.respondWith(Promise.resolve(new Response(
      "The local archive is read-only.", {status: 405}
    )));
    return;
  }
  const target = url.origin === self.location.origin && url.pathname.startsWith("/__external__/")
    ? "https://" + url.pathname.slice("/__external__/".length) + url.search
    : url.origin === self.location.origin
    ? originalOrigin + url.pathname + url.search
    : url.href;
  const headers = new Headers();
  if (event.request.headers.has("range")) {
    headers.set("range", event.request.headers.get("range"));
  }
  event.respondWith(fetch("/__mirror__?url=" + encodeURIComponent(target), {headers}));
});
