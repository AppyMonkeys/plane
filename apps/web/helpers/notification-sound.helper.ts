/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// The chime Plane plays when a desktop notification arrives while Plane is open.
//
// Browsers don't let a site pick the sound of an OS notification popup, so the service worker
// (public/sw.js) asks an open Plane window to play this instead, and falls back to the operating
// system's own sound when no window can. The chime is synthesised with Web Audio -- there is no
// audio file to ship or cache.

const STORAGE_KEY = "plane:notification-sound";

/** Message the service worker sends (with a reply port) when a push notification arrives. */
export const NOTIFICATION_SOUND_MESSAGE = "PLANE_NOTIFICATION_SOUND";

export const isNotificationSoundEnabled = (): boolean => {
  try {
    return localStorage.getItem(STORAGE_KEY) !== "off";
  } catch {
    return true;
  }
};

export const setNotificationSoundEnabled = (enabled: boolean): void => {
  try {
    if (enabled) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, "off");
  } catch {
    /* storage unavailable (private mode etc.) -- the choice just lasts until the page reloads */
  }
};

let audioContext: AudioContext | null = null;

const getAudioContext = (): AudioContext | null => {
  if (typeof window === "undefined") return null;
  if (!audioContext) {
    const AudioContextClass =
      window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextClass) return null;
    try {
      audioContext = new AudioContextClass();
    } catch {
      return null;
    }
  }
  return audioContext;
};

/**
 * Browsers keep audio suspended until the user has interacted with the page. Call this from a
 * user gesture (any click or key press) so a later notification is allowed to make a sound.
 */
export const unlockNotificationSound = (): void => {
  const context = getAudioContext();
  if (context?.state === "suspended") void context.resume().catch(() => undefined);
};

/**
 * Plays the chime: two short, soft sine notes.
 * @returns whether it could play -- false when the browser is still blocking audio for this page
 */
export const playNotificationChime = (): boolean => {
  const context = getAudioContext();
  if (!context || context.state !== "running") return false;

  const notes = [
    { frequency: 880, start: 0, duration: 0.16 },
    { frequency: 1174.66, start: 0.13, duration: 0.3 },
  ];
  const now = context.currentTime;

  notes.forEach(({ frequency, start, duration }) => {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = frequency;
    // quick fade in and a longer fade out, so the notes don't click
    gain.gain.setValueAtTime(0.0001, now + start);
    gain.gain.exponentialRampToValueAtTime(0.18, now + start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + start + duration);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(now + start);
    oscillator.stop(now + start + duration + 0.02);
  });

  return true;
};
