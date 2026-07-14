"""ntfy.sh notifications (solution-plan.md Step 10). notify() is a no-op
whenever NTFY_TOPIC is unset - the entire subsystem is optional."""

import requests
from django.conf import settings
from django.utils import timezone

from .models import NotificationLog, NotificationSetting

NTFY_BASE_URL = "https://ntfy.sh"

KINDS = ["missed_block", "review_reminder", "review_overdue", "follow_up_due", "recurring_overdue"]


def is_kind_enabled(kind):
    setting = NotificationSetting.objects.filter(kind=kind).first()
    return setting.enabled if setting else True  # no row yet = default on


def _already_sent_today(kind, ref_id):
    today = timezone.localtime().date()
    return NotificationLog.objects.filter(
        kind=kind, ref_id=ref_id, sent_at__date=today
    ).exists()


def _post_to_ntfy(title, message, url="", priority="default"):
    if not settings.NTFY_TOPIC:
        return False
    headers = {"Title": title, "Priority": priority}
    if url:
        headers["Click"] = url
    requests.post(
        f"{NTFY_BASE_URL}/{settings.NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers=headers,
        timeout=10,
    )
    return True


def notify(kind, title, message, url="", priority="default", ref_id=None, force=False):
    """POST to ntfy.sh/<NTFY_TOPIC>. Returns True if a notification was
    actually sent, False if skipped (unconfigured, toggled off, or already
    sent today for this kind+ref_id - the NotificationLog dedupe rule)."""
    if not is_kind_enabled(kind):
        return False
    if not force and _already_sent_today(kind, ref_id):
        return False
    if not _post_to_ntfy(title, message, url, priority):
        return False
    NotificationLog.objects.create(kind=kind, ref_id=ref_id)
    return True


def send_test_notification(kind):
    """Settings page 'test-fire' button - bypasses the enabled-toggle and
    the daily dedupe (the whole point is to check connectivity right now
    regardless of either), but still needs NTFY_TOPIC configured."""
    label = kind.replace("_", " ")
    return _post_to_ntfy(
        title=f"Test: {label}",
        message=f"This is a test notification for '{label}'.",
        priority="default",
    )
