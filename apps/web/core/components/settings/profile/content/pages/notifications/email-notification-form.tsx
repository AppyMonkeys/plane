/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { Controller, useForm } from "react-hook-form";
// plane imports
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { IUserEmailNotificationSettings } from "@plane/types";
import { Switch } from "@makeplane/propel/components/switch";
// components
import { SettingsControlItem } from "@/components/settings/control-item";
// helpers
import {
  disableBrowserPushNotifications,
  enableBrowserPushNotifications,
  isBrowserPushActiveHere,
  isBrowserPushSupported,
} from "@/helpers/browser-push-notification.helper";
// services
import { UserService } from "@/services/user.service";

type Props = {
  data: IUserEmailNotificationSettings;
};

// services
const userService = new UserService();

export const NotificationsProfileSettingsForm = observer(function NotificationsProfileSettingsForm(props: Props) {
  const { data } = props;
  // translation
  const { t } = useTranslation();
  // whether *this* browser is actually subscribed -- the browser_push preference
  // is per user and defaults to on, so it can't tell whether this device will
  // receive anything
  const [isPushActiveHere, setIsPushActiveHere] = useState(false);
  // form data
  const { control, reset } = useForm<IUserEmailNotificationSettings>({
    defaultValues: {
      ...data,
    },
  });

  const handleSettingChange = async (key: keyof IUserEmailNotificationSettings, value: boolean) => {
    try {
      await userService.updateCurrentUserEmailNotificationSettings({
        [key]: value,
      });
      setToast({
        title: t("success"),
        type: TOAST_TYPE.SUCCESS,
        message: t("email_notification_setting_updated_successfully"),
      });
    } catch (_error) {
      setToast({
        title: t("error"),
        type: TOAST_TYPE.ERROR,
        message: t("failed_to_update_email_notification_setting"),
      });
    }
  };

  const handleBrowserPushChange = async (value: boolean, onChange: (value: boolean) => void) => {
    try {
      if (value) {
        const enabled = await enableBrowserPushNotifications();
        if (!enabled) {
          setToast({
            title: t("error"),
            type: TOAST_TYPE.ERROR,
            message: t("browser_notifications_permission_denied"),
          });
          return;
        }
      } else {
        await disableBrowserPushNotifications();
      }
      await userService.updateCurrentUserEmailNotificationSettings({ browser_push: value });
      onChange(value);
      setIsPushActiveHere(value);
      setToast({
        title: t("success"),
        type: TOAST_TYPE.SUCCESS,
        message: t("browser_notification_setting_updated_successfully"),
      });
    } catch (_error) {
      setToast({
        title: t("error"),
        type: TOAST_TYPE.ERROR,
        message: t("failed_to_update_browser_notification_setting"),
      });
    }
  };

  useEffect(() => {
    reset(data);
  }, [reset, data]);

  useEffect(() => {
    void isBrowserPushActiveHere().then(setIsPushActiveHere);
  }, []);

  return (
    <div className="flex flex-col gap-y-1">
      {isBrowserPushSupported() && (
        <SettingsControlItem
          title={t("browser_notifications")}
          description={t("browser_notifications_description")}
          control={
            <Controller
              control={control}
              name="browser_push"
              render={({ field: { value, onChange } }) => (
                <Switch
                  size="sm"
                  checked={value && isPushActiveHere}
                  onCheckedChange={(newValue) => {
                    void handleBrowserPushChange(newValue, onChange);
                  }}
                  aria-label={t("browser_notifications")}
                />
              )}
            />
          }
        />
      )}
      <SettingsControlItem
        title={t("property_changes")}
        description={t("property_changes_description")}
        control={
          <Controller
            control={control}
            name="property_change"
            render={({ field: { value, onChange } }) => (
              <Switch
                size="sm"
                checked={value}
                onCheckedChange={(newValue) => {
                  onChange(newValue);
                  void handleSettingChange("property_change", newValue);
                }}
                aria-label={t("property_changes")}
              />
            )}
          />
        }
      />
      <SettingsControlItem
        title={t("state_change")}
        description={t("state_change_description")}
        control={
          <Controller
            control={control}
            name="state_change"
            render={({ field: { value, onChange } }) => (
              <Switch
                size="sm"
                checked={value}
                onCheckedChange={(newValue) => {
                  onChange(newValue);
                  void handleSettingChange("state_change", newValue);
                }}
                aria-label={t("state_change")}
              />
            )}
          />
        }
      />
      <div className="border-l-3 border-subtle-1 pl-3">
        <SettingsControlItem
          title={t("issue_completed")}
          description={t("issue_completed_description")}
          control={
            <Controller
              control={control}
              name="issue_completed"
              render={({ field: { value, onChange } }) => (
                <Switch
                  size="sm"
                  checked={value}
                  onCheckedChange={(newValue) => {
                    onChange(newValue);
                    void handleSettingChange("issue_completed", newValue);
                  }}
                  aria-label={t("issue_completed")}
                />
              )}
            />
          }
        />
      </div>
      <SettingsControlItem
        title={t("comments")}
        description={t("comments_description")}
        control={
          <Controller
            control={control}
            name="comment"
            render={({ field: { value, onChange } }) => (
              <Switch
                size="sm"
                checked={value}
                onCheckedChange={(newValue) => {
                  onChange(newValue);
                  void handleSettingChange("comment", newValue);
                }}
                aria-label={t("comments")}
              />
            )}
          />
        }
      />
      <SettingsControlItem
        title={t("mentions")}
        description={t("mentions_description")}
        control={
          <Controller
            control={control}
            name="mention"
            render={({ field: { value, onChange } }) => (
              <Switch
                size="sm"
                checked={value}
                onCheckedChange={(newValue) => {
                  onChange(newValue);
                  void handleSettingChange("mention", newValue);
                }}
                aria-label={t("mentions")}
              />
            )}
          />
        }
      />
    </div>
  );
});
