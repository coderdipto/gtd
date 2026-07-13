from datetime import timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Task


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
