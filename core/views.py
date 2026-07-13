from django.conf import settings
from django.http import FileResponse
from django.shortcuts import render


def stub(request, title):
    """Placeholder view until the real screen is built in its epic."""
    return render(request, "core/stub.html", {"page_title": title})


def service_worker(request):
    # Served from root (not /static/) so its scope covers the whole app.
    return FileResponse(
        open(settings.BASE_DIR / "static" / "js" / "service-worker.js", "rb"),
        content_type="application/javascript",
    )
