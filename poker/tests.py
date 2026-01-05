from unittest.mock import patch

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Participant, Room, Story

TEST_FERNET_KEY = Fernet.generate_key().decode("ascii")

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


class EstimateFilterTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.room = Room.objects.create(name="Filter Room")
        self.participant = Participant.objects.create(
            room=self.room,
            display_name="Facilitator",
            is_facilitator=True,
        )
        session = self.client.session
        session["org_email"] = "tester@welltech.com"
        session[f"p_{self.room.code}"] = self.participant.id
        session.save()

    def test_hide_estimated_stories_filters_room(self):
        Story.objects.create(room=self.room, title="Has estimate", jira_estimate="3")
        Story.objects.create(room=self.room, title="No estimate", jira_estimate="")

        self.room.hide_estimated_stories = True
        self.room.save(update_fields=["hide_estimated_stories"])

        resp = self.client.get(reverse("poker:room_detail", args=[self.room.code]))
        self.assertContains(resp, "No estimate")
        self.assertNotContains(resp, "Has estimate")


@override_settings(JIRA_TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY)
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

    @patch("poker.views.requests.get")
    def test_jira_original_estimate_fallback(self, mock_get):
        sprint_payload = {
            "values": [
                {
                    "id": 556,
                    "originBoardId": self.room.jira_board_id,
                    "startDate": "2024-01-02",
                }
            ]
        }
        config_payload = {"estimation": {"type": "none"}}
        search_payload = {
            "total": 1,
            "startAt": 0,
            "maxResults": 100,
            "issues": [
                {
                    "key": "ABC-2",
                    "fields": {
                        "summary": "Original estimate",
                        "issuetype": {"name": "Story"},
                        "timetracking": {
                            "originalEstimate": "2h",
                            "originalEstimateSeconds": 7200,
                        },
                        "timeoriginalestimate": 7200,
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
        self.assertEqual(story.jira_estimate, "2h")

        detail = self.client.get(reverse("poker:room_detail", args=[self.room.code]))
        self.assertContains(detail, "Est: 2h")


@override_settings(JIRA_TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY)
class JiraTokenEncryptionTests(TestCase):
    def test_jira_token_encrypted_at_rest(self):
        room = Room.objects.create(
            name="Secure Room",
            jira_base_url="https://jira.example",
            jira_email="jira@example.com",
            jira_token="super-secret",
            jira_project_key="SEC",
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT jira_token FROM poker_room WHERE id = %s", [room.id])
            raw = cursor.fetchone()[0]
        self.assertNotEqual(raw, "super-secret")
        self.assertTrue(raw.startswith("enc$"))
        room.refresh_from_db()
        self.assertEqual(room.jira_token, "super-secret")


@override_settings(JIRA_TOKEN_ENCRYPTION_KEY="not-a-valid-key")
class JiraTokenInvalidKeyTests(TestCase):
    def test_invalid_encryption_key_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            Room.objects.create(
                name="Broken Key Room",
                jira_base_url="https://jira.example",
                jira_email="jira@example.com",
                jira_token="super-secret",
                jira_project_key="SEC",
            )
