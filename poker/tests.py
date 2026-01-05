from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Participant, Room, Story


class _StubResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class SmokeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="password"
        )

    def test_root_redirects_to_org_login(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("poker:org_login"), resp["Location"])

    def test_org_login_page_renders(self):
        resp = self.client.get(reverse("poker:org_login"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Secure access")
        if settings.TURNSTILE_SITE_KEY:
            self.assertContains(resp, "cf-turnstile")

    def test_admin_login_template_used(self):
        resp = self.client.get("/admin/login/")
        self.assertEqual(resp.status_code, 200)
        if settings.TURNSTILE_SITE_KEY:
            self.assertContains(resp, "cf-turnstile")

    def test_room_creation_flow(self):
        session = self.client.session
        session["org_email"] = "tester@welltech.com"
        session.save()
        resp = self.client.post(reverse("poker:room_list"), {"name": "Smoke Room", "card_set": "fibonacci"})
        self.assertEqual(resp.status_code, 302)
        room = Room.objects.get(name="Smoke Room")
        self.assertIn(room.code, resp["Location"])


class JiraImportTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.room = Room.objects.create(
            name="Jira Room",
            jira_base_url="https://jira.example",
            jira_email="jira@example.com",
            jira_token="token",
            jira_project_key="ABC",
            jira_board_id=123,
        )
        self.participant = Participant.objects.create(
            room=self.room,
            display_name="Facilitator",
            is_facilitator=True,
        )
        session = self.client.session
        session["org_email"] = "tester@welltech.com"
        session[f"p_{self.room.code}"] = self.participant.id
        session.save()

    @patch("poker.views.requests.get")
    def test_jira_estimate_renders_on_story_card(self, mock_get):
        sprint_payload = {
            "values": [
                {
                    "id": 555,
                    "originBoardId": self.room.jira_board_id,
                    "startDate": "2024-01-01",
                }
            ]
        }
        config_payload = {
            "estimation": {
                "type": "field",
                "field": {"fieldId": "customfield_10016"},
            }
        }
        search_payload = {
            "total": 1,
            "startAt": 0,
            "maxResults": 100,
            "issues": [
                {
                    "key": "ABC-1",
                    "fields": {
                        "summary": "Estimate me",
                        "issuetype": {"name": "Story"},
                        "customfield_10016": 8,
                    },
                }
            ],
        }
        mock_get.side_effect = [
            _StubResponse(sprint_payload),
            _StubResponse(config_payload),
            _StubResponse(search_payload),
        ]

        resp = self.client.post(reverse("poker:jira_import_next_sprint", args=[self.room.code]))
        self.assertEqual(resp.status_code, 302)

        story = Story.objects.get(room=self.room)
        self.assertEqual(story.jira_estimate, "8")

        detail = self.client.get(reverse("poker:room_detail", args=[self.room.code]))
        self.assertContains(detail, "Est: 8")
