/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { BellRing, X } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
// helpers
import {
  enableBrowserPushNotifications,
  isBrowserPushSupported,
  syncBrowserPushSubscription,
} from "@/helpers/browser-push-notification.helper";
// services
import { UserService } from "@/services/user.service";

const userService = new UserService();

const PROMPT_DISMISSED_AT_KEY = "plane:browser-push-prompt-dismissed-at";
const PROMPT_SNOOZE_MS = 7 * 24 * 60 * 60 * 1000;

// Run the check once per page load, not on every workspace-layout remount.
let hasCheckedThisPageLoad = false;

const wasPromptDismissedRecently = (): boolean => {
  try {
    const dismissedAt = Number(localStorage.getItem(PROMPT_DISMISSED_AT_KEY));
    return !!dismissedAt && Date.now() - dismissedAt < PROMPT_SNOOZE_MS;
  } catch {
    return false;
  }
};

const rememberPromptDismissed = () => {
  try {
    localStorage.setItem(PROMPT_DISMISSED_AT_KEY, String(Date.now()));
  } catch {
    /* storage unavailable (private mode etc.) -- the prompt just comes back next load */
  }
};

/**
 * Keeps desktop (web push) notifications working for users who have them
 * enabled in their preferences (the default):
 * - permission already granted -> silently (re)subscribe this browser, e.g. a
 *   new device, cleared site data, or an expired subscription;
 * - permission not decided yet -> show a small prompt; browsers only allow the
 *   permission request from a user action, so it's behind an "Enable" button;
 * - permission denied -> nothing (the browser won't let us ask again).
 */
export function BrowserPushManager() {
  const { t } = useTranslation();
  const [showPrompt, setShowPrompt] = useState(false);
  const [isEnabling, setIsEnabling] = useState(false);

  useEffect(() => {
    if (hasCheckedThisPageLoad || !isBrowserPushSupported()) return;
    hasCheckedThisPageLoad = true;

    const check = async () => {
      try {
        const settings = await userService.currentUserEmailNotificationSettings();
        if (!settings?.browser_push) return;

        if (Notification.permission === "granted") {
          await syncBrowserPushSubscription();
        } else if (Notification.permission === "default" && !wasPromptDismissedRecently()) {
          setShowPrompt(true);
        }
      } catch (error) {
        console.error("Failed to check browser push notification status", error);
      }
    };
    void check();
  }, []);

  const handleEnable = async () => {
    setIsEnabling(true);
    const enabled = await enableBrowserPushNotifications();
    setIsEnabling(false);
    setShowPrompt(false);
    if (enabled) {
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: t("success"),
        message: t("browser_push_prompt_enabled"),
      });
    } else {
      // Denied or dismissed the browser's own permission dialog
      rememberPromptDismissed();
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("error"),
        message: t("browser_notifications_permission_denied"),
      });
    }
  };

  const handleDismiss = () => {
    rememberPromptDismissed();
    setShowPrompt(false);
  };

  if (!showPrompt) return null;

  return (
    <div
      role="dialog"
      aria-labelledby="browser-push-prompt-title"
      className="fixed right-4 bottom-4 z-30 w-80 max-w-[calc(100vw-2rem)] rounded-lg border border-subtle bg-surface-1 p-4 shadow-raised-200"
    >
      <button
        type="button"
        onClick={handleDismiss}
        className="absolute top-3 right-3 text-tertiary hover:text-secondary"
        aria-label={t("browser_push_prompt_later")}
      >
        <X className="size-4" />
      </button>
      <div className="flex gap-3 pr-5">
        <BellRing className="mt-0.5 size-5 flex-shrink-0 text-accent-primary" />
        <div className="flex flex-col gap-1">
          <p id="browser-push-prompt-title" className="text-13 font-medium text-primary">
            {t("browser_push_prompt_title")}
          </p>
          <p className="text-11 text-secondary">{t("browser_push_prompt_description")}</p>
        </div>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={handleDismiss}>
          {t("browser_push_prompt_later")}
        </Button>
        <Button variant="primary" size="sm" onClick={() => void handleEnable()} loading={isEnabling}>
          {t("browser_push_prompt_enable")}
        </Button>
      </div>
    </div>
  );
}
