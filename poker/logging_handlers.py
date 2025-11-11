from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.utils.log import AdminEmailHandler


class RateLimitedAdminEmailHandler(AdminEmailHandler):
    """
    AdminEmailHandler that rate-limits crash emails using the default cache.
    """

    def emit(self, record):
        rate_limit = getattr(settings, "ERROR_EMAIL_MAX_PER_WINDOW", None)
        window = getattr(settings, "ERROR_EMAIL_WINDOW_SECONDS", 300)

        if not rate_limit or rate_limit <= 0:
            return super().emit(record)

        cache_key = f"error-email-rate:{record.levelname}"
        count = cache.get(cache_key)
        if count is None:
            cache.set(cache_key, 1, timeout=window)
        elif count >= rate_limit:
            return
        else:
            cache.incr(cache_key)

        super().emit(record)
