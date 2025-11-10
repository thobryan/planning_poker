from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Room


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
