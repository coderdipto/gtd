import json
import time

from django.contrib.auth.decorators import login_not_required
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import CaptureToken, InboxItem

RATE_LIMIT_PER_MINUTE = 60


def _rate_limited(token_str):
    # cache.add() only sets the key if absent (atomic), and cache.incr() is an
    # atomic increment on the backend - together they avoid the read-then-write
    # race a plain get()/set() pair would have under concurrent requests. Note
    # this is still only atomic *within* one cache backend instance: the
    # default LocMemCache is per-process, so under a multi-worker deployment
    # (gunicorn) the real cap is "N/min per worker", not a single global N/min
    # - a shared backend (e.g. Redis) would be needed to close that gap.
    key = f"capture_rl:{token_str}:{int(time.time() // 60)}"
    cache.add(key, 0, timeout=61)
    count = cache.incr(key)
    return count > RATE_LIMIT_PER_MINUTE


@csrf_exempt
@login_not_required
@require_POST
def capture(request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return JsonResponse({"detail": "missing bearer token"}, status=401)
    token_str = auth.removeprefix("Bearer ").strip()

    try:
        token = CaptureToken.objects.get(token=token_str)
    except CaptureToken.DoesNotExist:
        return JsonResponse({"detail": "invalid token"}, status=401)

    if _rate_limited(token_str):
        return JsonResponse({"detail": "rate limit exceeded"}, status=429)

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "invalid json"}, status=400)

    title = (payload.get("title") or "").strip()
    if not title:
        return JsonResponse({"detail": "title is required"}, status=400)

    item = InboxItem.objects.create(
        title=title[:300],
        description=payload.get("description") or "",
        source="shortcut",
    )

    token.last_used_at = timezone.now()
    token.save(update_fields=["last_used_at"])

    return JsonResponse({"id": item.id}, status=201)
