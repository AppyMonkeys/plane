# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid
from types import SimpleNamespace

import pytest

from plane.bgtasks.web_push_task import build_push_payload

RECEIVER_ID = uuid.uuid4()


def notification(field, new_identifier, title="Varun added assignee Rohan"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        receiver_id=RECEIVER_ID,
        workspace=SimpleNamespace(slug="lokko"),
        entity_identifier=uuid.uuid4(),
        title=title,
        message_stripped="",
        data={
            "issue": {"identifier": "LOKKO", "sequence_id": 6628, "name": "Octopus: bubbles"},
            "issue_activity": {"field": field, "new_identifier": new_identifier},
        },
    )


@pytest.mark.unit
class TestBuildPushPayload:
    def test_being_assigned_shows_the_ticket_number_and_title(self):
        payload = build_push_payload(notification("assignees", str(RECEIVER_ID)))

        assert payload["title"] == "LOKKO-6628"
        assert payload["body"] == "Octopus: bubbles"
        assert payload["url"] == "/lokko/browse/LOKKO-6628/"

    def test_someone_else_being_assigned_keeps_the_activity_wording(self):
        payload = build_push_payload(notification("assignees", str(uuid.uuid4())))

        assert payload["title"] == "Varun added assignee Rohan"

    def test_other_activity_keeps_its_wording(self):
        payload = build_push_payload(notification("state", None, title="Varun set the state to Done"))

        assert payload["title"] == "Varun set the state to Done"
        assert payload["url"] == "/lokko/browse/LOKKO-6628/"

    def test_notification_without_work_item_details_still_builds(self):
        bare = notification("state", None, title=None)
        bare.data = None

        payload = build_push_payload(bare)

        assert payload["title"] == "Plane"
        assert payload["url"] == f"/lokko/browse/{bare.entity_identifier}/"
