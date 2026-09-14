/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * Small hand-written service worker (no build-time precache manifest, so it
 * deliberately never caches hashed JS/CSS bundles — those change on every
 * deploy and a stale cached one would break the app). It has two jobs:
 *
 * 1. Just by being registered (see core/lib/wrappers/service-worker-wrapper.tsx),
 *    it plus manifest.json is what makes browsers treat Plane as an
 *    installable PWA, and gives a cached app-shell fallback when offline.
 * 2. Show OS-level notification popups for Web Push messages sent by the
 *    backend (see apps/api/plane/bgtasks/web_push_task.py) and focus/open
 *    the relevant page when a user clicks one.
 */

const APP_SHELL_CACHE = "plane-app-shell-v1";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== APP_SHELL_CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

// Network-first for page navigations, with a cached-shell fallback when
// offline; everything else (hashed assets, API calls) goes straight to the
// network untouched.
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const responseCopy = response.clone();
        caches.open(APP_SHELL_CACHE).then((cache) => cache.put("/", responseCopy));
        return response;
      })
      .catch(() => caches.match("/").then((cached) => cached || Response.error()))
  );
});

self.addEventListener("push", (event) => {
  if (!event.data) return;

  let payload;
  try {
    payload = event.data.json();
  } catch (_error) {
    payload = { title: "Plane", body: event.data.text() };
  }

  const { title, body, url, notification_id: notificationId } = payload;

  event.waitUntil(
    self.registration.showNotification(title || "Plane", {
      body: body || "",
      icon: "/favicon/android-chrome-192x192.png",
      badge: "/favicon/android-chrome-192x192.png",
      tag: notificationId,
      data: { url: url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = event.notification.data?.url || "/";

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientsList) => {
      for (const client of clientsList) {
        if (client.url.includes(targetUrl) && "focus" in client) {
          return client.focus();
        }
      }
      if (clientsList.length > 0 && "focus" in clientsList[0]) {
        clientsList[0].navigate(targetUrl);
        return clientsList[0].focus();
      }
      return self.clients.openWindow(targetUrl);
    })
  );
});
