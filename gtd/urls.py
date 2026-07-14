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
