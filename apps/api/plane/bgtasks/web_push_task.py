# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json

# Third party imports
from celery import shared_task
from pywebpush import WebPushException, webpush

# Django imports
from django.conf import settings

# Module imports
from plane.db.models import UserNotificationPreference, WebPushSubscription
from plane.utils.exception_logger import log_exception

# HTTP statuses a push service returns when a subscription is gone for good
# (browser uninstalled, permission revoked, endpoint expired) — anything else
# (network blip, 5xx from the push service) is left alone and just logged.
_DEAD_SUBSCRIPTION_STATUSES = {404, 410}


@shared_task
def send_web_push_notifications(notification_ids):
    """Send a browser push notification for each of the given Notification
    ids, to every active WebPushSubscription of that notification's receiver,
    provided the receiver has browser push enabled."""
    if not settings.VAPID_PUBLIC_KEY or not settings.VAPID_PRIVATE_KEY:
        return

    # Local import to avoid a circular import with bgtasks.notification_task
    from plane.db.models import Notification

    notifications = Notification.objects.filter(pk__in=notification_ids).select_related(
        "workspace", "project"
    )
    if not notifications:
        return

    receiver_ids = {str(notification.receiver_id) for notification in notifications}
    enabled_receiver_ids = set(
        UserNotificationPreference.objects.filter(
            user_id__in=receiver_ids, browser_push=True
        ).values_list("user_id", flat=True)
    )
    enabled_receiver_ids = {str(user_id) for user_id in enabled_receiver_ids}

    subscriptions_by_user = {}
    for subscription in WebPushSubscription.objects.filter(
        user_id__in=enabled_receiver_ids, is_active=True
    ):
        subscriptions_by_user.setdefault(str(subscription.user_id), []).append(subscription)

    for notification in notifications:
        receiver_id = str(notification.receiver_id)
        if receiver_id not in enabled_receiver_ids:
            continue
        subscriptions = subscriptions_by_user.get(receiver_id, [])
        if not subscriptions:
            continue

        url = "/"
        if notification.workspace and notification.entity_identifier:
            url = f"/{notification.workspace.slug}/browse/{notification.entity_identifier}/"

        payload = json.dumps(
            {
                "title": notification.title or "Plane",
                "body": notification.message_stripped or "",
                "url": url,
                "notification_id": str(notification.id),
            }
        )

        for subscription in subscriptions:
            _send_to_subscription(subscription, payload)


def _send_to_subscription(subscription, payload):
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{settings.VAPID_ADMIN_EMAIL}"},
        )
    except WebPushException as e:
        status_code = e.response.status_code if e.response is not None else None
        if status_code in _DEAD_SUBSCRIPTION_STATUSES:
            subscription.is_active = False
            subscription.save(update_fields=["is_active"])
        else:
            log_exception(e, warning=True)
    except Exception as e:
        log_exception(e, warning=True)
