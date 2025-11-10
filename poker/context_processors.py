from django.conf import settings


def turnstile(request):
    """
    Expose Turnstile keys/flags to templates.
    """
    site_key = getattr(settings, "TURNSTILE_SITE_KEY", "")
    secret = getattr(settings, "TURNSTILE_SECRET_KEY", "")
    return {
        "TURNSTILE_SITE_KEY": site_key,
        "TURNSTILE_ENABLED": bool(site_key and secret),
    }
