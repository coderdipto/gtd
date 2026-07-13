import secrets

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import InboxItemForm
from .models import CaptureToken, InboxItem


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


def _capture_form_context():
    return {"form": InboxItemForm(), "recent": InboxItem.objects.order_by("-created_at")[:3]}


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
    if form.is_valid():
        item = form.save(commit=False)
        item.source = "web"
        item.save()
    context = _capture_form_context()
    context["just_captured"] = form.is_valid()
    context["from_modal"] = request.POST.get("from_modal") == "1"
    template = (
        "core/partials/capture_modal_form.html"
        if context["from_modal"]
        else "core/partials/capture_form.html"
    )
    return render(request, template, context)


# --- Inbox (Step 3) ---


@login_required
def inbox_page(request):
    items = InboxItem.objects.filter(processed_at__isnull=True).order_by("-created_at")
    return render(request, "core/inbox.html", {"items": items})


@login_required
@require_POST
def inbox_item_done(request, pk):
    item = get_object_or_404(InboxItem, pk=pk, processed_at__isnull=True)
    item.done_directly = True
    item.processed_at = timezone.now()
    item.save(update_fields=["done_directly", "processed_at"])
    return render(request, "core/partials/inbox_row_removed.html", {"item": item})


# --- Settings: capture tokens (Step 3) ---


@login_required
def settings_page(request):
    tokens = CaptureToken.objects.order_by("-id")
    return render(request, "core/settings.html", {"tokens": tokens})


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
