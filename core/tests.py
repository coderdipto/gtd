import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import CaptureToken, InboxItem, Task


class SmokeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("today"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_login_then_base_renders(self):
        self.client.login(username="sudipto", password="testpass123")
        response = self.client.get(reverse("today"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GTD")
        self.assertContains(response, "Today")


class TaskConstraintTests(TestCase):
    def test_project_cannot_have_a_parent(self):
        parent = Task.objects.create(title="Parent project", is_project=True)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Task.objects.create(title="Invalid", is_project=True, parent=parent)

    def test_non_project_subtask_is_allowed(self):
        parent = Task.objects.create(title="Parent project", is_project=True)
        child = Task.objects.create(title="Subtask", is_project=False, parent=parent)
        self.assertEqual(child.parent, parent)


class NextActionsTests(TestCase):
    def setUp(self):
        self.project = Task.objects.create(title="Ship v1.2", is_project=True)

    def test_flagged_subtask_wins(self):
        Task.objects.create(title="A", parent=self.project, sort_order=100)
        flagged = Task.objects.create(
            title="B", parent=self.project, sort_order=200, is_next_action=True
        )
        state, tasks = self.project.next_actions()
        self.assertEqual(state, "flagged")
        self.assertEqual(tasks, [flagged])

    def test_no_flagged_falls_back_to_first_incomplete_by_sort_order(self):
        second = Task.objects.create(title="B", parent=self.project, sort_order=200)
        first = Task.objects.create(title="A", parent=self.project, sort_order=100)
        state, tasks = self.project.next_actions()
        self.assertEqual(state, "implicit")
        self.assertEqual(tasks, [first])

    def test_no_incomplete_subtasks_needs_attention(self):
        Task.objects.create(
            title="Done", parent=self.project, completed_at=timezone.now()
        )
        state, tasks = self.project.next_actions()
        self.assertEqual(state, Task.NEEDS_ATTENTION)
        self.assertEqual(tasks, [])

    def test_project_with_no_subtasks_needs_attention(self):
        state, tasks = self.project.next_actions()
        self.assertEqual(state, Task.NEEDS_ATTENTION)
        self.assertEqual(tasks, [])

    def test_complete_blocked_without_force_when_subtasks_incomplete(self):
        Task.objects.create(title="A", parent=self.project)
        self.assertFalse(self.project.complete())
        self.assertIsNone(self.project.completed_at)

    def test_complete_with_force_completes_subtasks_too(self):
        sub = Task.objects.create(title="A", parent=self.project)
        self.assertTrue(self.project.complete(force=True))
        self.project.refresh_from_db()
        sub.refresh_from_db()
        self.assertIsNotNone(self.project.completed_at)
        self.assertIsNotNone(sub.completed_at)


class TrashPurgeTests(TestCase):
    def test_purgeable_returns_only_old_trashed_tasks(self):
        now = timezone.now()
        old = Task.objects.create(
            title="Old trash", list=Task.List.TRASH, trashed_at=now - timedelta(days=31)
        )
        recent = Task.objects.create(
            title="Recent trash", list=Task.List.TRASH, trashed_at=now - timedelta(days=5)
        )
        Task.objects.create(title="Not trashed")

        purgeable = Task.objects.purgeable(as_of=now)
        self.assertIn(old, purgeable)
        self.assertNotIn(recent, purgeable)


class CaptureApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.token = CaptureToken.objects.create(token="tok_abc123", label="iPhone")

    def test_missing_token_rejected(self):
        response = self.client.post(
            reverse("api_capture"),
            data=json.dumps({"title": "Buy milk"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_token_rejected(self):
        response = self.client.post(
            reverse("api_capture"),
            data=json.dumps({"title": "Buy milk"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer not-a-real-token",
        )
        self.assertEqual(response.status_code, 401)

    def test_valid_token_creates_inbox_item(self):
        response = self.client.post(
            reverse("api_capture"),
            data=json.dumps({"title": "Buy milk", "description": "2%"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token.token}",
        )
        self.assertEqual(response.status_code, 201)
        item_id = response.json()["id"]
        item = InboxItem.objects.get(pk=item_id)
        self.assertEqual(item.title, "Buy milk")
        self.assertEqual(item.description, "2%")
        self.assertEqual(item.source, "shortcut")
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)

    def test_missing_title_rejected(self):
        response = self.client.post(
            reverse("api_capture"),
            data=json.dumps({}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token.token}",
        )
        self.assertEqual(response.status_code, 400)

    def test_rate_limit_enforced(self):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {self.token.token}"}
        for _ in range(60):
            response = self.client.post(
                reverse("api_capture"),
                data=json.dumps({"title": "x"}),
                content_type="application/json",
                **headers,
            )
            self.assertEqual(response.status_code, 201)
        response = self.client.post(
            reverse("api_capture"),
            data=json.dumps({"title": "one too many"}),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 429)

    def test_endpoint_is_login_exempt(self):
        # No client.login() call anywhere in this class - if the endpoint required
        # login, every test above would 302 instead of returning its real status.
        response = self.client.post(reverse("api_capture"))
        self.assertNotEqual(response.status_code, 302)


class TwoMinuteRuleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_done_directly_never_becomes_a_task(self):
        item = InboxItem.objects.create(title="Reply to Anika")
        response = self.client.post(reverse("inbox_item_done", args=[item.id]))
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertTrue(item.done_directly)
        self.assertIsNotNone(item.processed_at)
        self.assertEqual(Task.objects.count(), 0)

    def test_done_item_drops_out_of_inbox_list(self):
        item = InboxItem.objects.create(title="Reply to Anika")
        self.client.post(reverse("inbox_item_done", args=[item.id]))
        response = self.client.get(reverse("inbox"))
        self.assertNotContains(response, "Reply to Anika")
