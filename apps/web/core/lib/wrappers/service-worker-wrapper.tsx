/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";

// Registers the app's service worker unconditionally (regardless of whether
// the user has opted into browser push notifications) so the browser treats
// Plane as an installable PWA — a registered service worker + a valid
// manifest + HTTPS is what makes the browser's install/"Add to Home Screen"
// prompt available. Safe to call on every mount: registration is a no-op
// once the same script URL is already registered.
export function ServiceWorkerWrapper() {
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch((error) => {
      console.error("Service worker registration failed", error);
    });
  }, []);

  return null;
}
