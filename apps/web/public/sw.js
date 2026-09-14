/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * Minimal service worker whose only job is to show OS-level notification
 * popups for Web Push messages sent by the backend (see
 * apps/api/plane/bgtasks/web_push_task.py) and focus/open the relevant page
 * when a user clicks one.
 */

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
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
