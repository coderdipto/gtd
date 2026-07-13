"""Google Calendar integration (solution-plan.md Step 8).

Every function/view here that talks to Google is gated on a connected
GoogleCredential existing - with none configured (no GOOGLE_CLIENT_ID/SECRET,
or no credential row yet), the app behaves as fully local-only. Disconnecting
wipes the credential + sync channels; existing TimeBlocks stay as ordinary
local rows (rollback path, task-breakdown.md Epic 8).
"""

import secrets
from datetime import datetime, timedelta, timezone as dt_timezone

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.decorators import login_not_required, login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import GoogleCredential, SyncChannel, TimeBlock

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]
GTD_CALENDAR_SUMMARY = "GTD"


# --- Encryption -----------------------------------------------------------


def _fernet():
    if not settings.FERNET_KEY:
        return None
    return Fernet(settings.FERNET_KEY.encode())


def encrypt_token(token):
    f = _fernet()
    if f is None:
        raise RuntimeError("FERNET_KEY is not configured")
    return f.encrypt(token.encode())


def decrypt_token(ciphertext):
    f = _fernet()
    if f is None:
        raise RuntimeError("FERNET_KEY is not configured")
    try:
        return f.decrypt(bytes(ciphertext)).decode()
    except InvalidToken:
        return None


def google_configured():
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.FERNET_KEY)


def get_credential():
    return GoogleCredential.objects.first()


# --- OAuth2 web flow (8a) ---------------------------------------------------


def _client_config():
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_OAUTH_REDIRECT],
        }
    }


def _build_flow(state=None):
    # Imported lazily so a dev environment without the client config/network
    # access can still import this module (used from tests via mocks).
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), scopes=CALENDAR_SCOPES, state=state)
    flow.redirect_uri = settings.GOOGLE_OAUTH_REDIRECT
    return flow


@login_required
@require_GET
def google_connect(request):
    if not google_configured():
        return HttpResponseBadRequest(
            "Google Calendar isn't configured (GOOGLE_CLIENT_ID/SECRET/FERNET_KEY missing)."
        )
    flow = _build_flow()
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    request.session["google_oauth_state"] = state
    return redirect(auth_url)


@login_required
@require_GET
def google_callback(request):
    state = request.GET.get("state")
    if not state or state != request.session.get("google_oauth_state"):
        return HttpResponseBadRequest("OAuth state mismatch.")
    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("Missing authorization code.")

    flow = _build_flow(state=state)
    flow.fetch_token(code=code)
    creds = flow.credentials

    GoogleCredential.objects.all().delete()  # singleton row
    credential = GoogleCredential.objects.create(refresh_token=encrypt_token(creds.refresh_token))

    client = GoogleCalendarClient(credential)
    gtd_calendar_id = client.create_gtd_calendar()
    credential.gtd_calendar_id = gtd_calendar_id
    credential.save(update_fields=["gtd_calendar_id"])
    register_watch_channel(credential, gtd_calendar_id)

    return redirect("settings")


@login_required
@require_POST
def google_disconnect(request):
    SyncChannel.objects.all().delete()
    GoogleCredential.objects.all().delete()
    return redirect("settings")


# --- Thin API client wrapper (mocked in tests) -----------------------------


class GoogleCalendarClient:
    """Wraps googleapiclient's Calendar v3 service for the handful of calls
    this app needs. Kept thin and mockable - tests patch its methods rather
    than hitting the real Google API."""

    def __init__(self, credential):
        self.credential = credential

    def _service(self):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        refresh_token = decrypt_token(self.credential.refresh_token)
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=CALENDAR_SCOPES,
        )
        return build("calendar", "v3", credentials=creds)

    def create_gtd_calendar(self):
        body = {"summary": GTD_CALENDAR_SUMMARY}
        result = self._service().calendars().insert(body=body).execute()
        return result["id"]

    def insert_event(self, calendar_id, body):
        return self._service().events().insert(calendarId=calendar_id, body=body).execute()

    def patch_event(self, calendar_id, event_id, body):
        return self._service().events().patch(calendarId=calendar_id, eventId=event_id, body=body).execute()

    def delete_event(self, calendar_id, event_id):
        return self._service().events().delete(calendarId=calendar_id, eventId=event_id).execute()

    def list_events(self, calendar_id, sync_token=None):
        kwargs = {"calendarId": calendar_id}
        if sync_token:
            kwargs["syncToken"] = sync_token
        return self._service().events().list(**kwargs).execute()

    def watch(self, calendar_id, channel_id, webhook_url, expiration_ms):
        body = {"id": channel_id, "type": "web_hook", "address": webhook_url, "expiration": str(expiration_ms)}
        return self._service().events().watch(calendarId=calendar_id, body=body).execute()

    def stop_channel(self, channel_id, resource_id):
        body = {"id": channel_id, "resourceId": resource_id}
        return self._service().channels().stop(body=body).execute()


def register_watch_channel(credential, calendar_id):
    client = GoogleCalendarClient(credential)
    channel_id = str(secrets.token_hex(16))
    webhook_url = settings.GOOGLE_OAUTH_REDIRECT.rsplit("/", 1)[0] + reverse("gcal_webhook")
    expiration_ms = int((timezone.now() + timedelta(days=7)).timestamp() * 1000)
    result = client.watch(calendar_id, channel_id, webhook_url, expiration_ms)
    SyncChannel.objects.create(
        calendar_id=calendar_id,
        channel_id=channel_id,
        resource_id=result.get("resourceId", ""),
        expiration=datetime.fromtimestamp(expiration_ms / 1000, tz=dt_timezone.utc),
    )
    return result


# --- Two-way sync (8c) ------------------------------------------------------


def _apply_event_to_block(event):
    """Matches a GCal event to its TimeBlock by gcal_event_id and applies
    the GCal-side change - last-write-wins by timestamp, GCal wins ties
    (solution-plan.md Step 8 decision log)."""
    event_id = event.get("id")
    block = TimeBlock.objects.filter(gcal_event_id=event_id).first()
    if not block:
        return  # unmatched events are ignored in v1

    if event.get("status") == "cancelled":
        block.delete()
        return

    updated_str = event.get("updated")
    if updated_str:
        gcal_updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
        if block.last_synced_at and block.last_synced_at > gcal_updated:
            return  # our side is strictly newer - GCal only wins on a tie or when it's newer

    start = event.get("start", {}).get("dateTime")
    end = event.get("end", {}).get("dateTime")
    if start:
        block.start = datetime.fromisoformat(start)
    if end:
        block.end = datetime.fromisoformat(end)
    block.gcal_etag = event.get("etag", "")
    block.last_synced_at = timezone.now()
    block.save(update_fields=["start", "end", "gcal_etag", "last_synced_at"])


def sync_calendar(credential):
    """Incremental sync via syncToken; on a 410 (expired/invalid token) falls
    back to a full resync and starts a fresh token."""
    from googleapiclient.errors import HttpError

    client = GoogleCalendarClient(credential)
    calendar_id = credential.gtd_calendar_id
    channel = SyncChannel.objects.filter(calendar_id=calendar_id).order_by("-id").first()
    sync_token = channel.sync_token if channel else None

    try:
        result = client.list_events(calendar_id, sync_token=sync_token)
    except HttpError as exc:
        if getattr(exc, "status_code", getattr(exc.resp, "status", None)) == 410:
            result = client.list_events(calendar_id, sync_token=None)  # full resync
        else:
            raise

    for event in result.get("items", []):
        _apply_event_to_block(event)

    new_sync_token = result.get("nextSyncToken")
    if new_sync_token and channel:
        channel.sync_token = new_sync_token
        channel.save(update_fields=["sync_token"])
    return len(result.get("items", []))


# --- Webhook (8c) ------------------------------------------------------------


@csrf_exempt
@login_not_required
@require_POST
def gcal_webhook(request):
    channel_id = request.headers.get("X-Goog-Channel-ID", "")
    resource_id = request.headers.get("X-Goog-Resource-ID", "")
    try:
        channel = SyncChannel.objects.filter(channel_id=channel_id, resource_id=resource_id).first()
    except (ValueError, ValidationError):
        # channel_id is a UUIDField - malformed input (e.g. a probing request)
        # should 404 like an unmatched channel, not 500.
        channel = None
    if not channel:
        return HttpResponse(status=404)

    credential = get_credential()
    if credential:
        sync_calendar(credential)
    return HttpResponse(status=200)
