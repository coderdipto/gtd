from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.urls import include, path

from core import api
from core.forms import StyledAuthenticationForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", LoginView.as_view(authentication_form=StyledAuthenticationForm), name="login"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("api/capture", api.capture, name="api_capture"),
    path("", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    # django-debug-toolbar (dev-only). Import-guarded to match settings.py: a
    # prod checkout never installs the package, so this include is skipped. Also
    # skipped under TESTING, in lockstep with the settings.py wiring, so the
    # namespace's presence matches whether the middleware is actually active.
    if not settings.TESTING:
        try:
            import debug_toolbar  # noqa: F401
        except ImportError:
            pass
        else:
            urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]
