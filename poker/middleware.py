from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse


class OrgAccessMiddleware:
    """
    Lightweight gatekeeper ensuring only authenticated org members can reach app views.
    We rely on a session key set by the OrgAccessForm and allow opt-out for selected routes.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_names = set(getattr(settings, "ORG_ACCESS_EXEMPT_URLNAMES", []))
        self.exempt_prefixes = [
            p for p in [getattr(settings, "STATIC_URL", "/static/"), getattr(settings, "MEDIA_URL", "/media/")] if p
        ]
        # Always allow admin site so superusers can still reach it.
        self.exempt_names.update({"org_login", "org_logout"})

    def __call__(self, request):
        if self._is_exempt_path(request):
            return self.get_response(request)

        if request.session.get("org_email"):
            return self.get_response(request)

        login_url = reverse("poker:org_login")
        if request.path == login_url:
            return self.get_response(request)

        query = urlencode({"next": request.get_full_path()})
        return redirect(f"{login_url}?{query}")

    def _is_exempt_path(self, request):
        path = request.path
        for prefix in self.exempt_prefixes:
            if prefix and path.startswith(prefix):
                return True
        try:
            match = resolve(path)
        except Resolver404:
            return False

        if match.app_name == "admin":
            return True

        full_name = f"{match.namespace}:{match.url_name}" if match.namespace else match.url_name
        return match.url_name in self.exempt_names or full_name in self.exempt_names
