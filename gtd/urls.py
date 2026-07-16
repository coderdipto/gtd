from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.templatetags.static import static as static_url
from django.urls import include, path
from django.views.decorators.cache import cache_control

from core import api
from core.forms import StyledAuthenticationForm


# Browsers auto-request /favicon.ico regardless of the <link rel="icon"> tag,
# which 404s on every page. Redirect it to the real static favicon (resolved at
# request time so it stays correct under prod's hashed-manifest storage).
@login_not_required
@cache_control(max_age=60 * 60 * 24 * 7)
def favicon(request):
    return redirect(static_url("icons/app/favicon.png"))


urlpatterns = [
    path("admin/", admin.site.urls),
    path("favicon.ico", favicon),
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
