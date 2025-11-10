from django.conf import settings


def turnstile(request):
    """
    Expose Turnstile keys/flags to templates.
    """
    enabled = bool(getattr(settings, "TURNSTILE_ENABLED", False) and settings.TURNSTILE_SITE_KEY)
    return {
        "TURNSTILE_SITE_KEY": settings.TURNSTILE_SITE_KEY if enabled else "",
        "TURNSTILE_ENABLED": enabled,
    }
