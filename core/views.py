import secrets

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import InboxItemForm
from .google_calendar import get_credential, google_configured
from .models import CaptureToken, InboxItem, NotificationSetting
from .notifications import KINDS, is_kind_enabled, send_test_notification


def stub(request, title):
    """Placeholder view until the real screen is built in its epic."""
    return render(request, "core/stub.html", {"page_title": title})


def service_worker(request):
    # Served from root (not /static/) so its scope covers the whole app.
    return FileResponse(
        open(settings.BASE_DIR / "static" / "js" / "service-worker.js", "rb"),
        content_type="application/javascript",
    )


# --- Capture (Step 3) ---


def _capture_form_context(form=None):
    return {
        "form": form or InboxItemForm(),
        "recent": InboxItem.objects.order_by("-created_at")[:3],
    }


def _unprocessed_inbox_items():
    return InboxItem.objects.filter(processed_at__isnull=True).order_by("-created_at")


@login_required
def capture_page(request):
    return render(request, "core/capture.html", _capture_form_context())


@login_required
def capture_modal(request):
    return render(request, "core/partials/capture_modal.html", _capture_form_context())


@login_required
@require_POST
def inbox_item_create(request):
    form = InboxItemForm(request.POST)
    just_captured = False
    if form.is_valid():
        item = form.save(commit=False)
        item.source = "web"
        item.save()
        just_captured = True
        form = InboxItemForm()  # fresh form for the next capture
    # On failure, the bound `form` (with its errors) is reused below instead
    # of being discarded, so the user sees why nothing was captured.
    context = _capture_form_context(form=form)
    context["just_captured"] = just_captured
    context["modal"] = request.POST.get("from_modal") == "1"
    html = render_to_string("core/partials/capture_form.html", context, request=request)
    if just_captured:
        # The capture form only swaps itself, so a capture from the modal
        # (or the /capture page) never touches the Inbox list, the header
        # trust strip, or the sidebar count sitting elsewhere in the page —
        # they'd otherwise only update on a manual refresh. OOB-swap all
        # three; htmx silently drops any fragment whose id isn't present on
        # whatever page the user actually captured from.
        html += render_to_string(
            "core/partials/inbox_body.html", {"items": _unprocessed_inbox_items(), "oob": True}, request=request
        )
        html += render_to_string("core/partials/trust_strip.html", {"oob": True}, request=request)
        html += render_to_string("core/partials/sidebar_inbox_count.html", {"oob": True}, request=request)
    return HttpResponse(html)


# --- Inbox (Step 3) ---


@login_required
def inbox_page(request):
    return render(request, "core/inbox.html", {"items": _unprocessed_inbox_items()})


@login_required
@require_POST
def inbox_item_done(request, pk):
    item = get_object_or_404(InboxItem, pk=pk, processed_at__isnull=True)
    item.done_directly = True
    item.processed_at = timezone.now()
    item.save(update_fields=["done_directly", "processed_at"])
    html = render_to_string("core/partials/inbox_row_removed.html", {"item": item}, request=request)
    # The row removes itself via its own Alpine fade, so only the counts
    # elsewhere on the page (trust strip, sidebar) need an OOB refresh here —
    # same staleness this row's own removal doesn't otherwise cause.
    html += render_to_string("core/partials/trust_strip.html", {"oob": True}, request=request)
    html += render_to_string("core/partials/sidebar_inbox_count.html", {"oob": True}, request=request)
    return HttpResponse(html)


# --- Settings: capture tokens (Step 3) ---


@login_required
def settings_page(request):
    tokens = CaptureToken.objects.order_by("-id")
    notification_kinds = [{"kind": k, "enabled": is_kind_enabled(k)} for k in KINDS]
    return render(
        request,
        "core/settings.html",
        {
            "tokens": tokens,
            "credential": get_credential(),
            "google_configured": google_configured(),
            "notification_kinds": notification_kinds,
            "ntfy_configured": bool(settings.NTFY_TOPIC),
        },
    )


@login_required
@require_POST
def notification_toggle(request, kind):
    setting, _created = NotificationSetting.objects.get_or_create(kind=kind, defaults={"enabled": True})
    setting.enabled = not setting.enabled
    setting.save(update_fields=["enabled"])
    return render(request, "core/partials/notification_row.html", {"kind": kind, "enabled": setting.enabled})


@login_required
@require_POST
def notification_test_fire(request, kind):
    sent = send_test_notification(kind)
    return render(
        request,
        "core/partials/notification_test_result.html",
        {"kind": kind, "sent": sent},
    )


@login_required
@require_POST
def capture_token_create(request):
    label = request.POST.get("label", "iPhone").strip() or "iPhone"
    token = CaptureToken.objects.create(token=secrets.token_urlsafe(32), label=label)
    tokens = CaptureToken.objects.order_by("-id")
    return render(
        request,
        "core/partials/token_list.html",
        {"tokens": tokens, "new_token": token},
    )


@login_required
@require_POST
def capture_token_revoke(request, pk):
    CaptureToken.objects.filter(pk=pk).delete()
    tokens = CaptureToken.objects.order_by("-id")
    return render(request, "core/partials/token_list.html", {"tokens": tokens})
