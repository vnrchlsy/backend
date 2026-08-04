import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure DRF throttle buckets (keyed by client IP in Django's LocMemCache,
    which is process-lifetime and not tied to per-test DB transactions) don't
    leak between tests -- otherwise an earlier request to one throttled view
    can silently consume budget shared by another view using the same scope."""
    cache.clear()
    yield
