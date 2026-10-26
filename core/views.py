"""Sonde de santé pour l'hébergeur / l'équilibreur de charge."""
import time

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache


@never_cache
def health(request):
    checks, ok = {}, True
    start = time.monotonic()
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"], ok = "error", False
    try:
        cache.set("health:ping", "1", 10)
        checks["cache"] = "ok" if cache.get("health:ping") == "1" else "error"
    except Exception:
        checks["cache"] = "error"
    ok = ok and checks["cache"] == "ok"
    checks["duration_ms"] = round((time.monotonic() - start) * 1000, 1)
    return JsonResponse({"status": "ok" if ok else "degraded", "checks": checks}, status=200 if ok else 503)
