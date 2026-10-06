/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
// helpers
import {
  NOTIFICATION_SOUND_MESSAGE,
  isNotificationSoundEnabled,
  playNotificationChime,
  unlockNotificationSound,
} from "@/helpers/notification-sound.helper";

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

  // Notification sound: when a push notification arrives the service worker asks an open window
  // to play the chime, and uses the reply to decide whether the OS popup should stay quiet.
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;

    const handleMessage = (event: MessageEvent) => {
      if ((event.data as { type?: string } | null)?.type !== NOTIFICATION_SOUND_MESSAGE) return;
      // muted here -> we have "handled" it by staying quiet; otherwise handled only if audio could play
      const handled = isNotificationSoundEnabled() ? playNotificationChime() : true;
      event.ports[0]?.postMessage({ handled });
    };
    navigator.serviceWorker.addEventListener("message", handleMessage);

    // browsers only allow sound after the user has interacted with the page
    const unlock = () => unlockNotificationSound();
    window.addEventListener("pointerdown", unlock, { passive: true });
    window.addEventListener("keydown", unlock, { passive: true });

    return () => {
      navigator.serviceWorker.removeEventListener("message", handleMessage);
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, []);

  return null;
}
