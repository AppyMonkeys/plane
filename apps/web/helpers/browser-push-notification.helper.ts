/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { UserService } from "@/services/user.service";

const userService = new UserService();

export const isBrowserPushSupported = (): boolean =>
  typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

// A VAPID public key (base64url) has to be converted to the Uint8Array form
// the Push API's applicationServerKey expects.
const urlBase64ToUint8Array = (base64String: string): Uint8Array => {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
};

/**
 * Makes sure this browser has a push subscription and that the server knows
 * about it. Only works once notification permission is already granted — it
 * never prompts. Safe to call repeatedly: the backend upserts by endpoint.
 * Returns true if this browser ends up subscribed.
 */
export const syncBrowserPushSubscription = async (): Promise<boolean> => {
  if (!isBrowserPushSupported() || Notification.permission !== "granted") return false;

  try {
    const registration = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;

    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      const { public_key } = await userService.getWebPushVAPIDPublicKey();
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(public_key),
      });
    }

    const subscriptionJSON = subscription.toJSON();
    if (!subscriptionJSON.endpoint || !subscriptionJSON.keys?.p256dh || !subscriptionJSON.keys?.auth) return false;

    await userService.createWebPushSubscription({
      endpoint: subscriptionJSON.endpoint,
      p256dh: subscriptionJSON.keys.p256dh,
      auth: subscriptionJSON.keys.auth,
      user_agent: navigator.userAgent,
    });
    return true;
  } catch (error) {
    console.error("Failed to enable browser push notifications", error);
    return false;
  }
};

/**
 * Requests notification permission (call from a user action, e.g. a button
 * click), then subscribes this browser and saves the subscription on the
 * server. Returns true on success, false if unsupported/denied/failed.
 */
export const enableBrowserPushNotifications = async (): Promise<boolean> => {
  if (!isBrowserPushSupported()) return false;

  const permission = await Notification.requestPermission();
  if (permission !== "granted") return false;

  return syncBrowserPushSubscription();
};

/**
 * Whether this particular browser will actually receive push notifications:
 * permission granted and an active push subscription. The user's
 * browser_push preference alone doesn't say anything about this device.
 */
export const isBrowserPushActiveHere = async (): Promise<boolean> => {
  if (!isBrowserPushSupported() || Notification.permission !== "granted") return false;
  try {
    const registration = await navigator.serviceWorker.getRegistration("/sw.js");
    return !!(await registration?.pushManager.getSubscription());
  } catch {
    return false;
  }
};

export const disableBrowserPushNotifications = async (): Promise<void> => {
  if (!isBrowserPushSupported()) return;

  try {
    const registration = await navigator.serviceWorker.getRegistration("/sw.js");
    const subscription = await registration?.pushManager.getSubscription();
    if (!subscription) return;

    const endpoint = subscription.endpoint;
    await subscription.unsubscribe();
    await userService.deleteWebPushSubscription(endpoint);
  } catch (error) {
    console.error("Failed to disable browser push notifications", error);
  }
};
