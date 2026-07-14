import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Area,
    CaptureToken,
    GoogleCredential,
    InboxItem,
    Note,
    NotificationLog,
    NotificationSetting,
    RecurringTemplate,
    ReviewConfig,
    ReviewSession,
    SyncChannel,
    Tag,
    Task,
    TimeBlock,
)
from core.notifications import KINDS, is_kind_enabled, notify
from core.recurring import build_rrule, parse_rrule
from core.reviews import WEEKLY_PHASES
from core.tagging import extract_tags, sync_tags_from_text

_TEST_FERNET_KEY = Fernet.generate_key().decode()

gcal_settings = override_settings(
    GOOGLE_CLIENT_ID="test-client-id",
    GOOGLE_CLIENT_SECRET="test-client-secret",
    GOOGLE_OAUTH_REDIRECT="http://testserver/google/callback",
    FERNET_KEY=_TEST_FERNET_KEY,
)


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


class TagParserTests(TestCase):
    def test_context_and_plain_tag(self):
        tags = list(extract_tags("Call mom @phone #family"))
        self.assertIn(("phone", True), tags)
        self.assertIn(("family", False), tags)

    def test_case_folded(self):
        tags = list(extract_tags("@Errand"))
        self.assertEqual(tags, [("errand", True)])

    def test_no_match_mid_word_email_or_url_fragment(self):
        # @/# only tag at the start of text or after whitespace, so an email
        # local part or a URL fragment doesn't get misread as a tag token.
        self.assertEqual(list(extract_tags("john@example.com")), [])
        self.assertEqual(list(extract_tags("see docs.com/page#comment")), [])

    def test_empty_text_yields_nothing(self):
        self.assertEqual(list(extract_tags("")), [])
        self.assertEqual(list(extract_tags(None)), [])

    def test_sync_creates_and_reuses_tags(self):
        task = Task.objects.create(title="Call mom @phone")
        sync_tags_from_text(task, task.title)
        self.assertEqual(Tag.objects.filter(name="phone", is_context=True).count(), 1)
        self.assertIn("phone", task.tags.values_list("name", flat=True))

        other = Task.objects.create(title="Call dad @phone")
        sync_tags_from_text(other, other.title)
        self.assertEqual(Tag.objects.filter(name="phone").count(), 1)

    def test_sync_is_additive_never_removes_existing_tags(self):
        task = Task.objects.create(title="Something #keep")
        sync_tags_from_text(task, task.title)
        kept_tag = Tag.objects.get(name="keep")
        sync_tags_from_text(task, "no tags here at all")
        self.assertIn(kept_tag, task.tags.all())

    def test_sync_across_multiple_texts_no_duplicate_tags(self):
        task = Task.objects.create(title="Title @same", description="Body @same")
        sync_tags_from_text(task, task.title, task.description)
        self.assertEqual(task.tags.filter(name="same").count(), 1)


class ClarifyWizardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_process_start_redirects_to_oldest_unprocessed_item(self):
        older = InboxItem.objects.create(title="Older")
        InboxItem.objects.create(title="Newer")
        response = self.client.get(reverse("inbox_process"))
        self.assertRedirects(response, reverse("clarify_actionable", args=[older.id]))

    def test_process_start_shows_finished_screen_when_empty(self):
        response = self.client.get(reverse("inbox_process"))
        self.assertTemplateUsed(response, "core/clarify/finished.html")
        self.assertContains(response, "Inbox zero")

    def test_no_cherry_picking_always_returns_oldest_regardless_of_pk(self):
        older = InboxItem.objects.create(title="Older")
        newer = InboxItem.objects.create(title="Newer")
        # Even asking for the actionable screen of the newer item directly
        # doesn't change which item process_start/inbox_process hands back.
        self.client.get(reverse("clarify_actionable", args=[newer.id]))
        response = self.client.get(reverse("inbox_process"))
        self.assertRedirects(response, reverse("clarify_actionable", args=[older.id]))

    def test_trash_path_creates_trashed_task_not_raw_discard(self):
        item = InboxItem.objects.create(title="Junk mail", description="spam")
        self.client.post(reverse("clarify_trash", args=[item.id]))
        item.refresh_from_db()
        self.assertIsNotNone(item.processed_at)
        task = Task.objects.get(title="Junk mail")
        self.assertEqual(task.list, Task.List.TRASH)
        self.assertIsNotNone(task.trashed_at)

    def test_done_path_marks_done_directly_never_creates_task(self):
        item = InboxItem.objects.create(title="Quick reply")
        self.client.post(reverse("clarify_done", args=[item.id]))
        item.refresh_from_db()
        self.assertTrue(item.done_directly)
        self.assertIsNotNone(item.processed_at)
        self.assertEqual(Task.objects.count(), 0)

    def test_someday_path_creates_someday_task_and_tags(self):
        item = InboxItem.objects.create(title="Learn pottery")
        response = self.client.post(
            reverse("clarify_someday", args=[item.id]),
            {"title": "Learn pottery @hobby", "description": ""},
        )
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(title="Learn pottery @hobby")
        self.assertEqual(task.list, Task.List.SOMEDAY)
        self.assertIn("hobby", task.tags.values_list("name", flat=True))
        item.refresh_from_db()
        self.assertIsNotNone(item.processed_at)

    def test_reference_path_creates_note(self):
        item = InboxItem.objects.create(title="Article link", description="https://example.com")
        response = self.client.post(
            reverse("clarify_reference", args=[item.id]),
            {"title": "Article link", "body": "https://example.com #reading"},
        )
        self.assertEqual(response.status_code, 302)
        note = Note.objects.get(title="Article link")
        self.assertIn("reading", note.tags.values_list("name", flat=True))
        item.refresh_from_db()
        self.assertIsNotNone(item.processed_at)

    def test_single_action_path_creates_next_task(self):
        item = InboxItem.objects.create(title="Email Bob")
        response = self.client.post(
            reverse("clarify_single", args=[item.id]),
            {"title": "Email Bob @email", "description": "", "horizon": Task.Horizon.ANYTIME},
        )
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(title="Email Bob @email")
        self.assertEqual(task.list, Task.List.NEXT)
        self.assertFalse(task.is_project)
        self.assertIn("email", task.tags.values_list("name", flat=True))

    def test_project_path_requires_at_least_one_subtask(self):
        item = InboxItem.objects.create(title="Plan trip")
        response = self.client.post(
            reverse("clarify_project", args=[item.id]),
            {"title": "Plan trip", "description": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "next action")
        self.assertFalse(Task.objects.filter(title="Plan trip").exists())
        item.refresh_from_db()
        self.assertIsNone(item.processed_at)

    def test_project_path_creates_project_with_flagged_first_subtask(self):
        item = InboxItem.objects.create(title="Plan trip")
        response = self.client.post(
            reverse("clarify_project", args=[item.id]),
            {
                "title": "Plan trip",
                "description": "",
                "subtask_title": ["Book flights", "Book hotel"],
            },
        )
        self.assertEqual(response.status_code, 302)
        project = Task.objects.get(title="Plan trip")
        self.assertTrue(project.is_project)
        subtasks = list(project.subtasks.order_by("sort_order"))
        self.assertEqual([s.title for s in subtasks], ["Book flights", "Book hotel"])
        self.assertTrue(subtasks[0].is_next_action)
        self.assertFalse(subtasks[1].is_next_action)

    def test_delegate_path_creates_waiting_task(self):
        item = InboxItem.objects.create(title="Get contract signed")
        response = self.client.post(
            reverse("clarify_delegate", args=[item.id]),
            {
                "title": "Get contract signed",
                "description": "",
                "waiting_on": "Legal team",
                "follow_up_after_days": 5,
            },
        )
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(title="Get contract signed")
        self.assertEqual(task.list, Task.List.WAITING)
        self.assertEqual(task.waiting_on, "Legal team")
        self.assertEqual(task.waiting_since, timezone.now().date())

    def test_form_screens_render_on_get_with_tag_typeahead_wired(self):
        # Regression check for the field_tagged.html partial (Alpine
        # tagTypeahead) added alongside the plain form fields - a broken
        # include there would 500 every GET to these screens.
        item = InboxItem.objects.create(title="Something")
        for name in (
            "clarify_someday",
            "clarify_reference",
            "clarify_single",
            "clarify_project",
            "clarify_delegate",
        ):
            response = self.client.get(reverse(name, args=[item.id]))
            self.assertEqual(response.status_code, 200, name)
            self.assertContains(response, "tagTypeahead(")

    def test_progress_counter_advances_across_the_session(self):
        first = InboxItem.objects.create(title="First")
        second = InboxItem.objects.create(title="Second")
        response = self.client.get(reverse("clarify_actionable", args=[first.id]))
        self.assertContains(response, "1 / 2")
        self.client.post(reverse("clarify_trash", args=[first.id]))
        response = self.client.get(reverse("clarify_actionable", args=[second.id]))
        self.assertContains(response, "2 / 2")


class TodayViewCompositionTests(TestCase):
    """The four inclusion rules from solution-plan.md Step 5."""

    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")
        self.today = timezone.localtime().date()

    def test_horizon_today_included(self):
        t = Task.objects.create(title="Horizon today", horizon=Task.Horizon.TODAY)
        response = self.client.get(reverse("today"))
        self.assertContains(response, t.title)

    def test_task_with_timeblock_today_included(self):
        t = Task.objects.create(title="Blocked today", horizon=Task.Horizon.ANYTIME)
        TimeBlock.objects.create(
            task=t,
            start=timezone.now().replace(hour=14, minute=0),
            end=timezone.now().replace(hour=15, minute=0),
        )
        response = self.client.get(reverse("today"))
        self.assertContains(response, t.title)

    def test_due_today_and_overdue_included(self):
        due_today = Task.objects.create(title="Due today", horizon=Task.Horizon.ANYTIME, due_date=self.today)
        overdue = Task.objects.create(
            title="Overdue task", horizon=Task.Horizon.ANYTIME, due_date=self.today - timedelta(days=3)
        )
        response = self.client.get(reverse("today"))
        self.assertContains(response, due_today.title)
        self.assertContains(response, overdue.title)

    def test_overdue_recurring_instance_included(self):
        template = RecurringTemplate.objects.create(title="Weekly thing", rrule="FREQ=WEEKLY")
        instance = Task.objects.create(
            title="Recurring instance",
            horizon=Task.Horizon.ANYTIME,
            recurring_template=template,
            occurrence_date=self.today - timedelta(days=1),
        )
        response = self.client.get(reverse("today"))
        self.assertContains(response, instance.title)

    def test_anytime_task_not_in_curated_but_in_anytime_section(self):
        t = Task.objects.create(title="Plain anytime task", horizon=Task.Horizon.ANYTIME)
        response = self.client.get(reverse("today"))
        self.assertContains(response, t.title)
        self.assertNotIn(t.id, [c.id for c in response.context["curated"]])
        self.assertIn(t.id, [a.id for a in response.context["anytime"]])

    def test_project_shells_excluded_from_today(self):
        Task.objects.create(title="A project", is_project=True, horizon=Task.Horizon.TODAY)
        response = self.client.get(reverse("today"))
        self.assertEqual(len(response.context["curated"]), 0)


class ReorderPersistenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")
        self.a = Task.objects.create(title="A", sort_order=100)
        self.b = Task.objects.create(title="B", sort_order=200)
        self.c = Task.objects.create(title="C", sort_order=300)

    def test_reorder_moves_task_after_specified_sibling(self):
        # Drag C to sit right after A (i.e. new order A, C, B).
        self.client.post(reverse("task_reorder", args=[self.c.id]), {"after": self.a.id})
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.c.refresh_from_db()
        self.assertTrue(self.a.sort_order < self.c.sort_order < self.b.sort_order)

    def test_reorder_to_front_when_no_after_given(self):
        self.client.post(reverse("task_reorder", args=[self.c.id]), {})
        self.a.refresh_from_db()
        self.c.refresh_from_db()
        self.assertTrue(self.c.sort_order < self.a.sort_order)

    def test_reorder_scoped_to_same_parent_and_list(self):
        project = Task.objects.create(title="Project", is_project=True)
        sub = Task.objects.create(title="Sub", parent=project, sort_order=100)
        # Reordering a top-level task must never touch a subtask's sort_order.
        self.client.post(reverse("task_reorder", args=[self.c.id]), {"after": self.a.id})
        sub.refresh_from_db()
        self.assertEqual(sub.sort_order, 100)


class RolloverCommandTests(TestCase):
    def test_today_horizon_always_carried_over(self):
        t = Task.objects.create(title="T", horizon=Task.Horizon.TODAY)
        call_command("rollover", "--as-of", "2026-07-15")  # a Wednesday
        t.refresh_from_db()
        self.assertEqual(t.carried_over_count, 1)

    def test_week_horizon_only_carried_over_on_monday(self):
        t = Task.objects.create(title="W", horizon=Task.Horizon.WEEK)
        call_command("rollover", "--as-of", "2026-07-15")  # Wednesday - not Monday
        t.refresh_from_db()
        self.assertEqual(t.carried_over_count, 0)

        call_command("rollover", "--as-of", "2026-07-13")  # a Monday
        t.refresh_from_db()
        self.assertEqual(t.carried_over_count, 1)

    def test_month_horizon_only_carried_over_on_first(self):
        t = Task.objects.create(title="M", horizon=Task.Horizon.MONTH)
        call_command("rollover", "--as-of", "2026-07-15")
        t.refresh_from_db()
        self.assertEqual(t.carried_over_count, 0)

        call_command("rollover", "--as-of", "2026-08-01")
        t.refresh_from_db()
        self.assertEqual(t.carried_over_count, 1)

    def test_completed_tasks_never_carried_over(self):
        t = Task.objects.create(title="Done", horizon=Task.Horizon.TODAY, completed_at=timezone.now())
        call_command("rollover", "--as-of", "2026-07-15")
        t.refresh_from_db()
        self.assertEqual(t.carried_over_count, 0)


class TagMergeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")
        self.source = Tag.objects.create(name="errand")
        self.target = Tag.objects.create(name="errands")
        self.task = Task.objects.create(title="Buy milk")
        self.task.tags.add(self.source)
        self.note = Note.objects.create(title="Shop list")
        self.note.tags.add(self.source)

    def test_merge_repoints_tasks_and_notes_and_deletes_source(self):
        self.client.post(reverse("tag_merge", args=[self.source.id]), {"target": self.target.id})
        self.assertFalse(Tag.objects.filter(id=self.source.id).exists())
        self.assertIn(self.target, self.task.tags.all())
        self.assertIn(self.target, self.note.tags.all())

    def test_merge_into_self_is_a_no_op_and_keeps_the_tag(self):
        self.client.post(reverse("tag_merge", args=[self.source.id]), {"target": self.source.id})
        self.assertTrue(Tag.objects.filter(id=self.source.id).exists())


class ProjectViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_project_with_no_subtasks_shows_stalled_badge(self):
        project = Task.objects.create(title="Empty project", is_project=True)
        response = self.client.get(reverse("projects"))
        self.assertContains(response, "stalled?")
        response = self.client.get(reverse("project_detail", args=[project.id]))
        self.assertContains(response, "No next action")

    def test_project_with_unflagged_subtasks_shows_no_next_badge(self):
        project = Task.objects.create(title="Project", is_project=True)
        Task.objects.create(title="Sub", parent=project)
        response = self.client.get(reverse("projects"))
        self.assertContains(response, "no next")

    def test_project_with_flagged_subtask_shows_no_stall_badge(self):
        project = Task.objects.create(title="Healthy project", is_project=True)
        Task.objects.create(title="Sub", parent=project, is_next_action=True)
        response = self.client.get(reverse("projects"))
        self.assertNotContains(response, "stalled?")
        self.assertNotContains(response, "no next")

    def test_add_subtask_auto_flags_first_one_only(self):
        project = Task.objects.create(title="Project", is_project=True)
        self.client.post(reverse("project_add_subtask", args=[project.id]), {"title": "First"})
        self.client.post(reverse("project_add_subtask", args=[project.id]), {"title": "Second"})
        subs = list(project.subtasks.order_by("sort_order"))
        self.assertTrue(subs[0].is_next_action)
        self.assertFalse(subs[1].is_next_action)

    def test_flag_next_toggle(self):
        project = Task.objects.create(title="Project", is_project=True)
        sub = Task.objects.create(title="Sub", parent=project)
        self.client.post(reverse("project_flag_next", args=[project.id, sub.id]))
        sub.refresh_from_db()
        self.assertTrue(sub.is_next_action)
        self.client.post(reverse("project_flag_next", args=[project.id, sub.id]))
        sub.refresh_from_db()
        self.assertFalse(sub.is_next_action)


class WaitingSomedayTrashTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_waiting_got_it_moves_to_next(self):
        t = Task.objects.create(title="Waiting task", list=Task.List.WAITING, waiting_since=date.today())
        self.client.post(reverse("waiting_got_it", args=[t.id]))
        t.refresh_from_db()
        self.assertEqual(t.list, Task.List.NEXT)
        self.assertIsNone(t.waiting_since)

    def test_waiting_nudge_resets_waiting_since(self):
        t = Task.objects.create(
            title="Waiting task", list=Task.List.WAITING, waiting_since=date.today() - timedelta(days=10)
        )
        self.client.post(reverse("waiting_nudge", args=[t.id]))
        t.refresh_from_db()
        self.assertEqual(t.waiting_since, date.today())

    def test_someday_activate_moves_to_next(self):
        t = Task.objects.create(title="Someday task", list=Task.List.SOMEDAY)
        self.client.post(reverse("someday_activate", args=[t.id]))
        t.refresh_from_db()
        self.assertEqual(t.list, Task.List.NEXT)

    def test_trash_restore(self):
        t = Task.objects.create(title="Trashed", list=Task.List.TRASH, trashed_at=timezone.now())
        self.client.post(reverse("task_restore", args=[t.id]))
        t.refresh_from_db()
        self.assertEqual(t.list, Task.List.NEXT)
        self.assertIsNone(t.trashed_at)

    def test_trash_row_hides_complete_circle(self):
        # Regression: task_row.html used `show_complete|default:True`, and
        # Django's `default` filter treats False as "unset" and substitutes
        # the default - silently turning an explicit show_complete=False
        # back into True. Trash rows must not render a complete button.
        Task.objects.create(title="Trashed", list=Task.List.TRASH, trashed_at=timezone.now())
        response = self.client.get(reverse("trash"))
        self.assertNotContains(response, 'aria-label="Complete"')

    def test_trash_purge_deletes_permanently(self):
        t = Task.objects.create(title="Trashed", list=Task.List.TRASH, trashed_at=timezone.now())
        self.client.post(reverse("task_purge", args=[t.id]))
        self.assertFalse(Task.objects.filter(id=t.id).exists())

    def test_task_move_to_trash_sets_trashed_at(self):
        t = Task.objects.create(title="Task")
        self.client.post(reverse("task_move", args=[t.id, "trash"]))
        t.refresh_from_db()
        self.assertEqual(t.list, Task.List.TRASH)
        self.assertIsNotNone(t.trashed_at)

    def test_task_complete_and_reopen(self):
        t = Task.objects.create(title="Task")
        self.client.post(reverse("task_complete", args=[t.id]))
        t.refresh_from_db()
        self.assertIsNotNone(t.completed_at)
        self.client.post(reverse("task_reopen", args=[t.id]))
        t.refresh_from_db()
        self.assertIsNone(t.completed_at)

    def test_project_complete_blocked_without_force(self):
        project = Task.objects.create(title="Project", is_project=True)
        Task.objects.create(title="Sub", parent=project)
        response = self.client.post(reverse("task_complete", args=[project.id]))
        self.assertEqual(response.status_code, 409)
        project.refresh_from_db()
        self.assertIsNone(project.completed_at)


class ScreenRenderSmokeTests(TestCase):
    """Every new Epic 5 screen renders without error, empty or populated."""

    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_all_screens_render_empty(self):
        for name in ("today", "week", "month", "tasks", "projects", "waiting", "someday", "trash", "tags"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

    def test_all_screens_render_populated(self):
        area = Area.objects.create(name="Home")
        tag = Tag.objects.create(name="errand", is_context=True)
        task = Task.objects.create(title="A next action", area=area, due_date=date.today())
        task.tags.add(tag)
        Task.objects.create(title="Waiting on someone", list=Task.List.WAITING, waiting_since=date.today())
        Task.objects.create(title="Someday maybe", list=Task.List.SOMEDAY)
        Task.objects.create(title="Trashed thing", list=Task.List.TRASH, trashed_at=timezone.now())
        project = Task.objects.create(title="A project", is_project=True)
        Task.objects.create(title="A subtask", parent=project, is_next_action=True)

        for name in ("today", "week", "month", "tasks", "projects", "waiting", "someday", "trash", "tags"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

        response = self.client.get(reverse("project_detail", args=[project.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A subtask")


class NoteSearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_search_matches_body_text(self):
        Note.objects.create(title="Recipe", body="A great sourdough starter guide.")
        Note.objects.create(title="Unrelated", body="Something else entirely.")
        response = self.client.get(reverse("notes"), {"q": "sourdough"})
        self.assertContains(response, "Recipe")
        self.assertNotContains(response, "Unrelated")

    def test_search_matches_title_text(self):
        Note.objects.create(title="Sourdough starter guide", body="")
        response = self.client.get(reverse("notes"), {"q": "starter"})
        self.assertContains(response, "Sourdough starter guide")

    def test_trashed_notes_excluded_from_list_and_search(self):
        Note.objects.create(title="Gone", body="findme", trashed_at=timezone.now())
        response = self.client.get(reverse("notes"))
        self.assertNotContains(response, "Gone")
        response = self.client.get(reverse("notes"), {"q": "findme"})
        self.assertNotContains(response, "Gone")

    def test_note_create_and_tag_parsing(self):
        self.client.post(reverse("note_create"), {"title": "Shopping", "body": "Milk @errand #home"})
        note = Note.objects.get(title="Shopping")
        names = set(note.tags.values_list("name", flat=True))
        self.assertEqual(names, {"errand", "home"})

    def test_note_update_renders_markdown(self):
        note = Note.objects.create(title="Doc", body="plain")
        self.client.post(reverse("note_update", args=[note.id]), {"title": "Doc", "body": "# Heading\n\nSome *text*"})
        response = self.client.get(reverse("note_detail", args=[note.id]))
        self.assertContains(response, "<h1>Heading</h1>")

    def test_note_delete_is_soft(self):
        note = Note.objects.create(title="To trash", body="")
        self.client.post(reverse("note_delete", args=[note.id]))
        note.refresh_from_db()
        self.assertIsNotNone(note.trashed_at)
        self.assertTrue(Note.objects.filter(id=note.id).exists())


class TaskToNoteConversionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_conversion_copies_fields_tags_and_trashes_task(self):
        tag = Tag.objects.create(name="reading")
        task = Task.objects.create(title="Interesting article", description="Some notes about it")
        task.tags.add(tag)

        self.client.post(reverse("task_convert_to_note", args=[task.id]))

        note = Note.objects.get(title="Interesting article")
        self.assertEqual(note.body, "Some notes about it")
        self.assertIn(tag, note.tags.all())

        task.refresh_from_db()
        self.assertEqual(task.list, Task.List.TRASH)
        self.assertIsNotNone(task.trashed_at)


class InboxReferenceConversionTests(TestCase):
    """Re-confirms Epic 4's Reference path lands in the real Notes module now
    that it exists (task-breakdown.md Epic 6: 'verify here')."""

    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_reference_path_note_is_searchable(self):
        item = InboxItem.objects.create(title="Article", description="Long read about gardening")
        self.client.post(
            reverse("clarify_reference", args=[item.id]),
            {"title": "Article", "body": "Long read about gardening #reading"},
        )
        response = self.client.get(reverse("notes"), {"q": "gardening"})
        self.assertContains(response, "Article")


_MEDIA_TMPDIR = tempfile.mkdtemp(prefix="gtd_test_media_")


@override_settings(MEDIA_ROOT=_MEDIA_TMPDIR)
class NoteScreenSmokeTests(TestCase):
    # Attachment uploads hit real FileSystemStorage (not transactional like
    # the DB), so MEDIA_ROOT is redirected to a throwaway temp dir for this
    # class - otherwise test runs leave files behind in the real media/.
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_notes_and_create_render_empty(self):
        for name in ("notes", "note_create"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

    def test_note_detail_renders_with_attachment(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        note = Note.objects.create(title="Doc", body="body text")
        self.client.post(
            reverse("note_attachment_upload", args=[note.id]),
            {"file": SimpleUploadedFile("notes.txt", b"hello")},
        )
        response = self.client.get(reverse("note_detail", args=[note.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "notes.txt")

    def test_oversized_attachment_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        note = Note.objects.create(title="Doc", body="")
        big_file = SimpleUploadedFile("big.bin", b"x" * (21 * 1024 * 1024))
        self.client.post(reverse("note_attachment_upload", args=[note.id]), {"file": big_file})
        self.assertEqual(note.attachments.count(), 0)


class RRuleRoundTripTests(TestCase):
    def test_weekly_with_byday_and_interval_round_trips(self):
        rrule_str = build_rrule("WEEKLY", byday=["TU", "TH"], interval=2)
        self.assertEqual(rrule_str, "FREQ=WEEKLY;BYDAY=TU,TH;INTERVAL=2")
        parsed = parse_rrule(rrule_str)
        self.assertEqual(parsed, {"freq": "WEEKLY", "byday": ["TU", "TH"], "interval": 2})

    def test_daily_with_default_interval_round_trips(self):
        rrule_str = build_rrule("DAILY")
        self.assertEqual(rrule_str, "FREQ=DAILY")
        parsed = parse_rrule(rrule_str)
        self.assertEqual(parsed, {"freq": "DAILY", "byday": [], "interval": 1})

    def test_monthly_with_interval_round_trips(self):
        rrule_str = build_rrule("MONTHLY", interval=3)
        parsed = parse_rrule(rrule_str)
        self.assertEqual(parsed["freq"], "MONTHLY")
        self.assertEqual(parsed["interval"], 3)


class MaterializeRecurringTests(TestCase):
    def setUp(self):
        self.template = RecurringTemplate.objects.create(
            title="Water plants", rrule=build_rrule("WEEKLY", byday=["MO", "TH"])
        )

    def test_creates_instances_within_window(self):
        call_command("materialize_recurring", "--as-of", "2026-07-13")  # Monday
        instances = Task.objects.filter(recurring_template=self.template)
        self.assertGreater(instances.count(), 0)
        for t in instances:
            self.assertEqual(t.list, Task.List.NEXT)
            self.assertIn(t.occurrence_date.strftime("%a"), ("Mon", "Thu"))

    def test_todays_occurrence_gets_today_horizon_future_gets_anytime(self):
        call_command("materialize_recurring", "--as-of", "2026-07-13")  # Monday
        todays = Task.objects.get(recurring_template=self.template, occurrence_date=date(2026, 7, 13))
        self.assertEqual(todays.horizon, Task.Horizon.TODAY)
        future = Task.objects.get(recurring_template=self.template, occurrence_date=date(2026, 7, 16))  # Thursday
        self.assertEqual(future.horizon, Task.Horizon.ANYTIME)

    def test_running_twice_does_not_duplicate(self):
        call_command("materialize_recurring", "--as-of", "2026-07-13")
        first_count = Task.objects.filter(recurring_template=self.template).count()
        call_command("materialize_recurring", "--as-of", "2026-07-13")
        second_count = Task.objects.filter(recurring_template=self.template).count()
        self.assertEqual(first_count, second_count)

    def test_advances_and_extends_window_on_next_run(self):
        call_command("materialize_recurring", "--as-of", "2026-07-13")
        first_count = Task.objects.filter(recurring_template=self.template).count()
        call_command("materialize_recurring", "--as-of", "2026-07-20")
        second_count = Task.objects.filter(recurring_template=self.template).count()
        self.assertGreater(second_count, first_count)

    def test_inactive_template_not_materialized(self):
        self.template.active = False
        self.template.save(update_fields=["active"])
        call_command("materialize_recurring", "--as-of", "2026-07-13")
        self.assertEqual(Task.objects.filter(recurring_template=self.template).count(), 0)

    def test_unique_constraint_prevents_duplicate_occurrence(self):
        Task.objects.create(
            recurring_template=self.template, occurrence_date=date(2026, 7, 13), title="x"
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Task.objects.create(
                    recurring_template=self.template, occurrence_date=date(2026, 7, 13), title="y"
                )


class OverduePileUpTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")
        self.template = RecurringTemplate.objects.create(title="Standup", rrule="FREQ=DAILY")
        self.overdue1 = Task.objects.create(
            recurring_template=self.template, occurrence_date=date(2026, 7, 10), title="Standup"
        )
        self.overdue2 = Task.objects.create(
            recurring_template=self.template, occurrence_date=date(2026, 7, 11), title="Standup"
        )
        self.not_overdue = Task.objects.create(
            recurring_template=self.template, occurrence_date=date(2026, 7, 20), title="Standup"
        )

    def test_overdue_badge_shown_on_task_row(self):
        response = self.client.get(reverse("recurring_detail", args=[self.template.id]))
        self.assertContains(response, "overdue since")
        self.assertEqual(response.context["overdue_count"], 2)

    def test_complete_all_overdue(self):
        self.client.post(reverse("recurring_complete_overdue", args=[self.template.id]))
        self.overdue1.refresh_from_db()
        self.overdue2.refresh_from_db()
        self.not_overdue.refresh_from_db()
        self.assertIsNotNone(self.overdue1.completed_at)
        self.assertIsNotNone(self.overdue2.completed_at)
        self.assertIsNone(self.not_overdue.completed_at)

    def test_trash_all_overdue(self):
        self.client.post(reverse("recurring_trash_overdue", args=[self.template.id]))
        self.overdue1.refresh_from_db()
        self.not_overdue.refresh_from_db()
        self.assertEqual(self.overdue1.list, Task.List.TRASH)
        self.assertEqual(self.not_overdue.list, Task.List.NEXT)

    def test_completing_one_instance_does_not_affect_others(self):
        self.overdue1.complete()
        self.overdue2.refresh_from_db()
        self.assertIsNone(self.overdue2.completed_at)


class RecurringScreensSmokeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_list_and_create_render_empty(self):
        for name in ("recurring", "recurring_create"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

    def test_create_then_detail_and_edit_render(self):
        response = self.client.post(
            reverse("recurring_create"),
            {"title": "Standup", "freq": "WEEKLY", "byday": ["MO", "WE", "FR"], "interval": "1"},
        )
        self.assertEqual(response.status_code, 302)
        template = RecurringTemplate.objects.get(title="Standup")
        self.assertEqual(template.rrule, "FREQ=WEEKLY;BYDAY=MO,WE,FR")

        for name in ("recurring_detail", "recurring_edit"):
            response = self.client.get(reverse(name, args=[template.id]))
            self.assertEqual(response.status_code, 200, name)

    def test_create_without_title_reshows_form_with_error(self):
        response = self.client.post(reverse("recurring_create"), {"title": "", "freq": "DAILY"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Title is required")
        self.assertFalse(RecurringTemplate.objects.exists())

    def test_deactivate_and_reactivate(self):
        template = RecurringTemplate.objects.create(title="X", rrule="FREQ=DAILY")
        self.client.post(reverse("recurring_deactivate", args=[template.id]))
        template.refresh_from_db()
        self.assertFalse(template.active)
        self.client.post(reverse("recurring_activate", args=[template.id]))
        template.refresh_from_db()
        self.assertTrue(template.active)


class RecurringTemplateGcalLinkageTests(TestCase):
    """core/recurring.py::_sync_gcal_event - the RecurringTemplate's own
    standing-block GCal event (distinct from per-instance TimeBlocks, which
    are deliberately never created for recurring tasks)."""

    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_noop_without_credential(self):
        response = self.client.post(
            reverse("recurring_create"),
            {
                "title": "Standup",
                "freq": "DAILY",
                "block_start_time": "09:00",
                "block_duration_min": "15",
            },
        )
        self.assertEqual(response.status_code, 302)
        template = RecurringTemplate.objects.get(title="Standup")
        self.assertEqual(template.gcal_event_id, "")

    @gcal_settings
    @patch("core.recurring.GoogleCalendarClient.insert_event")
    def test_standing_block_creates_recurring_gcal_event(self, mock_insert):
        GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
        mock_insert.return_value = {"id": "recurring-evt-1"}
        response = self.client.post(
            reverse("recurring_create"),
            {
                "title": "Standup",
                "freq": "DAILY",
                "block_start_time": "09:00",
                "block_duration_min": "15",
            },
        )
        self.assertEqual(response.status_code, 302)
        template = RecurringTemplate.objects.get(title="Standup")
        self.assertEqual(template.gcal_event_id, "recurring-evt-1")
        body = mock_insert.call_args.args[1]
        self.assertEqual(body["recurrence"], ["RRULE:FREQ=DAILY"])

    @gcal_settings
    @patch("core.recurring.GoogleCalendarClient.delete_event")
    def test_deactivating_deletes_the_gcal_event(self, mock_delete):
        GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
        template = RecurringTemplate.objects.create(
            title="Standup",
            rrule="FREQ=DAILY",
            block_start_time="09:00",
            block_duration_min=15,
            gcal_event_id="recurring-evt-1",
        )
        self.client.post(reverse("recurring_deactivate", args=[template.id]))
        mock_delete.assert_called_once_with("cal1", "recurring-evt-1")
        template.refresh_from_db()
        self.assertEqual(template.gcal_event_id, "")

    @gcal_settings
    @patch("core.recurring.GoogleCalendarClient.patch_event")
    def test_editing_patches_existing_gcal_event(self, mock_patch):
        GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
        template = RecurringTemplate.objects.create(
            title="Standup",
            rrule="FREQ=DAILY",
            block_start_time="09:00",
            block_duration_min=15,
            gcal_event_id="recurring-evt-1",
        )
        self.client.post(
            reverse("recurring_edit", args=[template.id]),
            {
                "title": "Standup (updated)",
                "freq": "DAILY",
                "block_start_time": "10:00",
                "block_duration_min": "30",
            },
        )
        mock_patch.assert_called_once()
        self.assertEqual(mock_patch.call_args.args[:2], ("cal1", "recurring-evt-1"))

    def test_template_without_standing_block_never_calls_gcal(self):
        with gcal_settings, patch("core.recurring.GoogleCalendarClient.insert_event") as mock_insert:
            GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
            self.client.post(reverse("recurring_create"), {"title": "No block", "freq": "WEEKLY"})
            mock_insert.assert_not_called()


@gcal_settings
class EncryptionTests(TestCase):
    def test_round_trip(self):
        from core.google_calendar import decrypt_token, encrypt_token

        ciphertext = encrypt_token("my-refresh-token")
        self.assertEqual(decrypt_token(ciphertext), "my-refresh-token")

    def test_encrypt_without_fernet_key_raises(self):
        from core.google_calendar import encrypt_token

        with override_settings(FERNET_KEY=""):
            with self.assertRaises(RuntimeError):
                encrypt_token("x")


@gcal_settings
class GoogleConnectFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_connect_redirects_to_google_when_configured(self):
        response = self.client.get(reverse("google_connect"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("accounts.google.com", response.url)

    def test_connect_rejected_when_not_configured(self):
        with override_settings(GOOGLE_CLIENT_ID=""):
            response = self.client.get(reverse("google_connect"))
            self.assertEqual(response.status_code, 400)

    def test_callback_rejects_state_mismatch(self):
        session = self.client.session
        session["google_oauth_state"] = "expected-state"
        session.save()
        response = self.client.get(reverse("google_callback"), {"state": "wrong-state", "code": "abc"})
        self.assertEqual(response.status_code, 400)

    @patch("core.google_calendar.register_watch_channel")
    @patch("core.google_calendar.GoogleCalendarClient.create_gtd_calendar")
    @patch("core.google_calendar._build_flow")
    def test_callback_success_creates_credential_and_calendar(self, mock_build_flow, mock_create_cal, mock_register):
        session = self.client.session
        session["google_oauth_state"] = "matching-state"
        session.save()

        mock_flow = MagicMock()
        mock_flow.credentials.refresh_token = "the-refresh-token"
        mock_build_flow.return_value = mock_flow
        mock_create_cal.return_value = "gtd-calendar-id"

        response = self.client.get(reverse("google_callback"), {"state": "matching-state", "code": "auth-code"})
        self.assertEqual(response.status_code, 302)

        credential = GoogleCredential.objects.get()
        self.assertEqual(credential.gtd_calendar_id, "gtd-calendar-id")
        from core.google_calendar import decrypt_token

        self.assertEqual(decrypt_token(credential.refresh_token), "the-refresh-token")
        mock_register.assert_called_once()

    def test_disconnect_wipes_credential_and_channels(self):
        credential = GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
        SyncChannel.objects.create(
            calendar_id="cal1", channel_id="11111111-1111-1111-1111-111111111111", resource_id="res1", expiration=timezone.now()
        )
        self.client.post(reverse("google_disconnect"))
        self.assertFalse(GoogleCredential.objects.exists())
        self.assertFalse(SyncChannel.objects.exists())
        credential  # keep reference alive for clarity


@gcal_settings
class GoogleCalendarClientTests(TestCase):
    def setUp(self):
        self.credential = GoogleCredential.objects.create(
            refresh_token=b"irrelevant-for-this-test", gtd_calendar_id="cal1"
        )

    def _client_with_mocked_service(self):
        from core.google_calendar import GoogleCalendarClient

        client = GoogleCalendarClient(self.credential)
        client._service = MagicMock()
        return client

    def test_insert_event_calls_events_insert(self):
        client = self._client_with_mocked_service()
        client._service.return_value.events.return_value.insert.return_value.execute.return_value = {"id": "evt1"}
        result = client.insert_event("cal1", {"summary": "Test"})
        client._service.return_value.events.return_value.insert.assert_called_once_with(
            calendarId="cal1", body={"summary": "Test"}
        )
        self.assertEqual(result["id"], "evt1")

    def test_patch_event_calls_events_patch(self):
        client = self._client_with_mocked_service()
        client._service.return_value.events.return_value.patch.return_value.execute.return_value = {}
        client.patch_event("cal1", "evt1", {"summary": "✓ Done"})
        client._service.return_value.events.return_value.patch.assert_called_once_with(
            calendarId="cal1", eventId="evt1", body={"summary": "✓ Done"}
        )

    def test_delete_event_calls_events_delete(self):
        client = self._client_with_mocked_service()
        client._service.return_value.events.return_value.delete.return_value.execute.return_value = {}
        client.delete_event("cal1", "evt1")
        client._service.return_value.events.return_value.delete.assert_called_once_with(
            calendarId="cal1", eventId="evt1"
        )


@gcal_settings
class WebhookValidationTests(TestCase):
    def setUp(self):
        self.credential = GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
        self.channel = SyncChannel.objects.create(
            calendar_id="cal1", channel_id="11111111-1111-1111-1111-111111111111", resource_id="res1", expiration=timezone.now()
        )

    def test_unknown_channel_rejected(self):
        response = self.client.post(
            reverse("gcal_webhook"), HTTP_X_GOOG_CHANNEL_ID="nope", HTTP_X_GOOG_RESOURCE_ID="nope"
        )
        self.assertEqual(response.status_code, 404)

    @patch("core.google_calendar.sync_calendar")
    def test_valid_channel_triggers_sync(self, mock_sync):
        response = self.client.post(
            reverse("gcal_webhook"),
            HTTP_X_GOOG_CHANNEL_ID="11111111-1111-1111-1111-111111111111",
            HTTP_X_GOOG_RESOURCE_ID="res1",
        )
        self.assertEqual(response.status_code, 200)
        mock_sync.assert_called_once_with(self.credential)

    def test_webhook_is_login_exempt(self):
        # No client.login() anywhere in this class - a login-required endpoint
        # would 302 to the login page instead of returning 404/200.
        response = self.client.post(reverse("gcal_webhook"))
        self.assertNotEqual(response.status_code, 302)


@gcal_settings
class SyncConflictAndResyncTests(TestCase):
    def setUp(self):
        self.credential = GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
        self.task = Task.objects.create(title="Deep work")

    def _event(self, event_id, start, end, updated, status=None):
        event = {
            "id": event_id,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
            "updated": updated,
            "etag": '"etag1"',
        }
        if status:
            event["status"] = status
        return event

    def test_gcal_wins_on_tie(self):
        from core.google_calendar import _apply_event_to_block

        tie_time = datetime(2026, 7, 15, 10, 0, tzinfo=dt_timezone.utc)
        block = TimeBlock.objects.create(
            task=self.task,
            start=datetime(2026, 7, 15, 9, 0, tzinfo=dt_timezone.utc),
            end=datetime(2026, 7, 15, 9, 30, tzinfo=dt_timezone.utc),
            gcal_event_id="evt1",
            last_synced_at=tie_time,
        )
        event = self._event("evt1", "2026-07-15T14:00:00+00:00", "2026-07-15T14:30:00+00:00", "2026-07-15T10:00:00Z")
        _apply_event_to_block(event)
        block.refresh_from_db()
        self.assertEqual(block.start.hour, 14)

    def test_local_wins_when_strictly_newer(self):
        from core.google_calendar import _apply_event_to_block

        block = TimeBlock.objects.create(
            task=self.task,
            start=datetime(2026, 7, 15, 9, 0, tzinfo=dt_timezone.utc),
            end=datetime(2026, 7, 15, 9, 30, tzinfo=dt_timezone.utc),
            gcal_event_id="evt1",
            last_synced_at=datetime(2026, 7, 15, 12, 0, tzinfo=dt_timezone.utc),
        )
        event = self._event("evt1", "2026-07-15T14:00:00+00:00", "2026-07-15T14:30:00+00:00", "2026-07-15T10:00:00Z")
        _apply_event_to_block(event)
        block.refresh_from_db()
        self.assertEqual(block.start.hour, 9)  # untouched - our side was newer

    def test_cancelled_status_deletes_block(self):
        from core.google_calendar import _apply_event_to_block

        block = TimeBlock.objects.create(
            task=self.task,
            start=timezone.now(),
            end=timezone.now() + timedelta(hours=1),
            gcal_event_id="evt1",
        )
        event = self._event(
            "evt1", "2026-07-15T14:00:00+00:00", "2026-07-15T14:30:00+00:00", "2026-07-15T10:00:00Z", status="cancelled"
        )
        _apply_event_to_block(event)
        self.assertFalse(TimeBlock.objects.filter(id=block.id).exists())

    def test_unmatched_event_is_ignored(self):
        from core.google_calendar import _apply_event_to_block

        event = self._event("no-such-event", "2026-07-15T14:00:00+00:00", "2026-07-15T14:30:00+00:00", "2026-07-15T10:00:00Z")
        _apply_event_to_block(event)  # should not raise

    @patch("core.google_calendar.GoogleCalendarClient.list_events")
    def test_410_triggers_full_resync(self, mock_list_events):
        from googleapiclient.errors import HttpError

        from core.google_calendar import sync_calendar

        SyncChannel.objects.create(
            calendar_id="cal1", channel_id="11111111-1111-1111-1111-111111111111", resource_id="res1", expiration=timezone.now(),
            sync_token="stale-token",
        )
        error_resp = MagicMock(status=410)
        mock_list_events.side_effect = [HttpError(error_resp, b"Gone"), {"items": [], "nextSyncToken": "fresh"}]

        sync_calendar(self.credential)
        self.assertEqual(mock_list_events.call_count, 2)
        first_call_kwargs = mock_list_events.call_args_list[0].kwargs
        second_call_kwargs = mock_list_events.call_args_list[1].kwargs
        self.assertEqual(first_call_kwargs.get("sync_token"), "stale-token")
        self.assertIsNone(second_call_kwargs.get("sync_token"))


class MissedBlockCommandTests(TestCase):
    def test_past_scheduled_block_incomplete_task_becomes_missed(self):
        task = Task.objects.create(title="Gym")
        block = TimeBlock.objects.create(
            task=task, start=timezone.now() - timedelta(hours=2), end=timezone.now() - timedelta(hours=1)
        )
        call_command("detect_missed_blocks")
        block.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(block.status, TimeBlock.Status.MISSED)
        self.assertEqual(task.missed_block_count, 1)

    def test_completed_task_block_not_marked_missed(self):
        task = Task.objects.create(title="Gym", completed_at=timezone.now())
        block = TimeBlock.objects.create(
            task=task, start=timezone.now() - timedelta(hours=2), end=timezone.now() - timedelta(hours=1)
        )
        call_command("detect_missed_blocks")
        block.refresh_from_db()
        self.assertEqual(block.status, TimeBlock.Status.SCHEDULED)

    def test_future_block_untouched(self):
        task = Task.objects.create(title="Gym")
        block = TimeBlock.objects.create(
            task=task, start=timezone.now() + timedelta(hours=1), end=timezone.now() + timedelta(hours=2)
        )
        call_command("detect_missed_blocks")
        block.refresh_from_db()
        self.assertEqual(block.status, TimeBlock.Status.SCHEDULED)


class RetitleOnCompleteTests(TestCase):
    def test_completing_task_marks_blocks_completed_without_credential(self):
        task = Task.objects.create(title="Write report")
        block = TimeBlock.objects.create(task=task, start=timezone.now(), end=timezone.now() + timedelta(hours=1))
        task.complete()
        block.refresh_from_db()
        self.assertEqual(block.status, TimeBlock.Status.COMPLETED)

    @gcal_settings
    @patch("core.timeblocks.GoogleCalendarClient.patch_event")
    def test_completing_task_retitles_gcal_event_when_connected(self, mock_patch):
        credential = GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
        task = Task.objects.create(title="Write report")
        TimeBlock.objects.create(
            task=task, start=timezone.now(), end=timezone.now() + timedelta(hours=1), gcal_event_id="evt1"
        )
        task.complete()
        mock_patch.assert_called_once_with("cal1", "evt1", {"summary": "✓ Write report"})
        credential.refresh_from_db()  # keep reference alive for clarity


class TimeblockViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")
        self.task = Task.objects.create(title="Focus block")

    def test_create_without_credential_is_local_only(self):
        response = self.client.post(
            reverse("timeblock_create", args=[self.task.id]),
            {"start": "2026-07-15T09:00", "end": "2026-07-15T10:00"},
        )
        self.assertEqual(response.status_code, 200)
        block = TimeBlock.objects.get(task=self.task)
        self.assertEqual(block.gcal_event_id, "")

    @gcal_settings
    @patch("core.timeblocks.GoogleCalendarClient.insert_event")
    def test_create_with_credential_stores_gcal_event_id(self, mock_insert):
        GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
        mock_insert.return_value = {"id": "evt1", "etag": '"e1"'}
        self.client.post(
            reverse("timeblock_create", args=[self.task.id]),
            {"start": "2026-07-15T09:00", "end": "2026-07-15T10:00"},
        )
        block = TimeBlock.objects.get(task=self.task)
        self.assertEqual(block.gcal_event_id, "evt1")

    def test_update_changes_start_end(self):
        block = TimeBlock.objects.create(
            task=self.task, start=timezone.now(), end=timezone.now() + timedelta(hours=1)
        )
        self.client.post(
            reverse("timeblock_update", args=[block.id]),
            {"start": "2026-07-16T09:00:00+00:00", "end": "2026-07-16T10:00:00+00:00"},
        )
        block.refresh_from_db()
        self.assertEqual(block.start.day, 16)

    def test_delete_removes_block(self):
        block = TimeBlock.objects.create(
            task=self.task, start=timezone.now(), end=timezone.now() + timedelta(hours=1)
        )
        self.client.post(reverse("timeblock_delete", args=[block.id]))
        self.assertFalse(TimeBlock.objects.filter(id=block.id).exists())


class CalendarScreenSmokeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_calendar_page_renders(self):
        response = self.client.get(reverse("calendar_page"))
        self.assertEqual(response.status_code, 200)

    def test_events_json_includes_blocks(self):
        task = Task.objects.create(title="Focus block")
        TimeBlock.objects.create(task=task, start=timezone.now(), end=timezone.now() + timedelta(hours=1))
        response = self.client.get(reverse("calendar_events_json"))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Focus block")

    def test_settings_shows_not_connected_by_default(self):
        response = self.client.get(reverse("settings"))
        self.assertContains(response, "Not connected")


class RenewChannelsAndSyncCommandTests(TestCase):
    def test_no_credential_is_a_safe_noop(self):
        call_command("renew_gcal_channels")
        call_command("sync_gcal")  # neither should raise

    @gcal_settings
    @patch("core.management.commands.renew_gcal_channels.register_watch_channel")
    def test_expiring_channel_gets_renewed(self, mock_register):
        credential = GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
        SyncChannel.objects.create(
            calendar_id="cal1",
            channel_id="11111111-1111-1111-1111-111111111111",
            resource_id="res1",
            expiration=timezone.now() + timedelta(hours=1),  # well within the 48h renewal window
        )
        call_command("renew_gcal_channels")
        mock_register.assert_called_once()
        self.assertFalse(SyncChannel.objects.filter(channel_id="11111111-1111-1111-1111-111111111111").exists())
        credential.refresh_from_db()  # keep reference alive for clarity

    @gcal_settings
    @patch("core.management.commands.sync_gcal.sync_calendar")
    def test_sync_gcal_calls_sync_when_connected(self, mock_sync):
        credential = GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
        call_command("sync_gcal")
        mock_sync.assert_called_once_with(credential)


class ReviewSetupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_onboarding_banner_shows_until_all_four_configured(self):
        response = self.client.get(reverse("review_dashboard"))
        self.assertContains(response, "Set up all four review cadences")
        ReviewConfig.objects.create(cadence="weekly")
        ReviewConfig.objects.create(cadence="monthly")
        ReviewConfig.objects.create(cadence="quarterly")
        ReviewConfig.objects.create(cadence="yearly")
        response = self.client.get(reverse("review_dashboard"))
        self.assertNotContains(response, "Set up all four review cadences")

    def test_config_save_creates_config(self):
        self.client.post(
            reverse("review_config_save", args=["weekly"]),
            {"weekday": "4", "time": "16:00", "duration_min": "60"},
        )
        config = ReviewConfig.objects.get(cadence="weekly")
        self.assertEqual(config.weekday, 4)
        self.assertEqual(config.duration_min, 60)

    @gcal_settings
    @patch("core.reviews.GoogleCalendarClient.insert_event")
    def test_config_save_creates_gcal_event_when_connected(self, mock_insert):
        GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
        mock_insert.return_value = {"id": "review-evt-1"}
        self.client.post(
            reverse("review_config_save", args=["weekly"]),
            {"weekday": "4", "time": "16:00", "duration_min": "60"},
        )
        config = ReviewConfig.objects.get(cadence="weekly")
        self.assertEqual(config.gcal_event_id, "review-evt-1")
        body = mock_insert.call_args.args[1]
        self.assertIn("RRULE:FREQ=WEEKLY", body["recurrence"][0])

    @gcal_settings
    @patch("core.reviews.GoogleCalendarClient.delete_event")
    def test_config_delete_removes_gcal_event(self, mock_delete):
        GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
        ReviewConfig.objects.create(cadence="weekly", gcal_event_id="review-evt-1")
        self.client.post(reverse("review_config_delete", args=["weekly"]))
        mock_delete.assert_called_once_with("cal1", "review-evt-1")
        self.assertFalse(ReviewConfig.objects.filter(cadence="weekly").exists())


class WeeklyWizardResumeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_start_creates_session_at_first_phase(self):
        response = self.client.get(reverse("review_weekly_start"))
        self.assertRedirects(response, reverse("review_weekly_phase", args=["get_clear"]))
        session = ReviewSession.objects.get(cadence="weekly")
        self.assertEqual(session.phase_state["phase"], "get_clear")

    def test_visiting_wrong_phase_redirects_to_current(self):
        self.client.get(reverse("review_weekly_start"))
        response = self.client.get(reverse("review_weekly_phase", args=["creative"]))
        self.assertRedirects(response, reverse("review_weekly_phase", args=["get_clear"]))

    def test_advancing_persists_and_resumes(self):
        self.client.get(reverse("review_weekly_start"))
        self.client.post(reverse("review_weekly_phase", args=["get_clear"]), {"next": "1"})
        session = ReviewSession.objects.get(cadence="weekly")
        self.assertEqual(session.phase_state["phase"], "projects")
        # A fresh "start" call resumes at the same phase rather than restarting.
        response = self.client.get(reverse("review_weekly_start"))
        self.assertRedirects(response, reverse("review_weekly_phase", args=["projects"]))

    def test_mind_sweep_captures_to_inbox_without_advancing(self):
        self.client.get(reverse("review_weekly_start"))
        self.client.post(reverse("review_weekly_phase", args=["get_clear"]), {"mind_sweep": "Buy milk\nCall dentist"})
        self.assertEqual(InboxItem.objects.filter(source="review").count(), 2)
        session = ReviewSession.objects.get(cadence="weekly")
        self.assertEqual(session.phase_state["phase"], "get_clear")


class WeeklyCarryoverGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")
        self.client.get(reverse("review_weekly_start"))
        session = ReviewSession.objects.get(cadence="weekly")
        session.phase_state = {"phase": "carryover"}
        session.save()

    def test_cannot_advance_past_unresolved_carryover(self):
        Task.objects.create(title="Stale", carried_over_count=3)
        self.client.post(reverse("review_weekly_phase", args=["carryover"]), {"next": "1"})
        session = ReviewSession.objects.get(cadence="weekly")
        self.assertEqual(session.phase_state["phase"], "carryover")

    def test_can_advance_once_all_resolved(self):
        self.client.post(reverse("review_weekly_phase", args=["carryover"]), {"next": "1"})
        session = ReviewSession.objects.get(cadence="weekly")
        self.assertEqual(session.phase_state["phase"], "waiting")

    def test_keep_resets_counter_and_shows_next_item(self):
        first = Task.objects.create(title="A", carried_over_count=2, sort_order=1)
        Task.objects.create(title="B", carried_over_count=1, sort_order=2)
        self.client.post(reverse("review_carryover_resolve", args=[first.id, "keep"]))
        first.refresh_from_db()
        self.assertEqual(first.carried_over_count, 0)
        response = self.client.get(reverse("review_weekly_phase", args=["carryover"]))
        self.assertContains(response, "B")

    def test_demote_sets_anytime_horizon(self):
        task = Task.objects.create(title="A", carried_over_count=2, horizon=Task.Horizon.WEEK)
        self.client.post(reverse("review_carryover_resolve", args=[task.id, "demote"]))
        task.refresh_from_db()
        self.assertEqual(task.horizon, Task.Horizon.ANYTIME)
        self.assertEqual(task.carried_over_count, 0)

    def test_someday_and_trash_actions(self):
        someday_task = Task.objects.create(title="A", carried_over_count=1)
        trash_task = Task.objects.create(title="B", carried_over_count=1)
        self.client.post(reverse("review_carryover_resolve", args=[someday_task.id, "someday"]))
        self.client.post(reverse("review_carryover_resolve", args=[trash_task.id, "trash"]))
        someday_task.refresh_from_db()
        trash_task.refresh_from_db()
        self.assertEqual(someday_task.list, Task.List.SOMEDAY)
        self.assertEqual(trash_task.list, Task.List.TRASH)
        self.assertIsNotNone(trash_task.trashed_at)


class EisenhowerDropTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")
        self.project = Task.objects.create(title="Redesign site", is_project=True)
        self.next_task = Task.objects.create(
            title="Draft mockup", parent=self.project, is_next_action=True
        )

    def test_q1_shows_commitment_when_due_soon(self):
        self.next_task.due_date = date.today()
        self.next_task.save(update_fields=["due_date"])
        response = self.client.post(reverse("review_eisenhower_drop", args=[self.project.id, "q1"]))
        self.assertContains(response, "already committed")

    def test_q1_prompts_when_no_commitment(self):
        response = self.client.post(reverse("review_eisenhower_drop", args=[self.project.id, "q1"]))
        self.assertContains(response, "Add a due date")

    def test_q2_shows_slot_picker_then_schedules(self):
        response = self.client.post(reverse("review_eisenhower_drop", args=[self.project.id, "q2"]))
        self.assertContains(response, "slot_start")
        response = self.client.post(
            reverse("review_eisenhower_drop", args=[self.project.id, "q2"]),
            {"slot_start": "2026-07-20T09:00"},
        )
        self.assertContains(response, "scheduled")
        self.next_task.refresh_from_db()
        self.assertIsNotNone(self.next_task.q2_week)
        self.assertTrue(TimeBlock.objects.filter(task=self.next_task).exists())

    def test_q3_shows_choice_then_delegates(self):
        response = self.client.post(reverse("review_eisenhower_drop", args=[self.project.id, "q3"]))
        self.assertContains(response, "Delegate")
        self.client.post(
            reverse("review_eisenhower_drop", args=[self.project.id, "q3"]),
            {"action": "waiting", "waiting_on": "Design team"},
        )
        self.next_task.refresh_from_db()
        self.assertEqual(self.next_task.list, Task.List.WAITING)
        self.assertEqual(self.next_task.waiting_on, "Design team")

    def test_q3_someday_action_parks_whole_project(self):
        self.client.post(
            reverse("review_eisenhower_drop", args=[self.project.id, "q3"]), {"action": "someday"}
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.list, Task.List.SOMEDAY)

    def test_q4_shows_choice_then_trashes(self):
        response = self.client.post(reverse("review_eisenhower_drop", args=[self.project.id, "q4"]))
        self.assertContains(response, "Trash")
        self.client.post(
            reverse("review_eisenhower_drop", args=[self.project.id, "q4"]), {"action": "trash"}
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.list, Task.List.TRASH)
        self.assertIsNotNone(self.project.trashed_at)

    def test_q4_someday_action(self):
        self.client.post(
            reverse("review_eisenhower_drop", args=[self.project.id, "q4"]), {"action": "someday"}
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.list, Task.List.SOMEDAY)


class Big3AndFinishTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")
        self.client.get(reverse("review_weekly_start"))
        session = ReviewSession.objects.get(cadence="weekly")
        session.phase_state = {"phase": "creative"}
        session.save()

    def test_big3_auto_clears_previous_stars(self):
        old_star = Task.objects.create(title="Old star", big3=True)
        new_pick = Task.objects.create(title="New pick")
        self.client.post(reverse("review_weekly_phase", args=["creative"]), {"set_big3": "1", "big3": [new_pick.id]})
        old_star.refresh_from_db()
        new_pick.refresh_from_db()
        self.assertFalse(old_star.big3)
        self.assertTrue(new_pick.big3)

    def test_big3_capped_at_three(self):
        tasks = [Task.objects.create(title=f"T{i}") for i in range(5)]
        self.client.post(
            reverse("review_weekly_phase", args=["creative"]),
            {"set_big3": "1", "big3": [t.id for t in tasks]},
        )
        self.assertEqual(Task.objects.filter(big3=True).count(), 3)

    def test_capture_box_creates_inbox_items(self):
        self.client.post(reverse("review_weekly_phase", args=["creative"]), {"capture": "New idea\nAnother one"})
        self.assertEqual(InboxItem.objects.filter(source="review").count(), 2)

    def test_finish_sets_completed_at_and_streak(self):
        response = self.client.post(reverse("review_weekly_phase", args=["creative"]), {"finish": "1"})
        session = ReviewSession.objects.get(cadence="weekly")
        self.assertIsNotNone(session.completed_at)
        self.assertEqual(session.stats_snapshot["streak"], 1)
        self.assertContains(response, "1")

    def test_streak_increments_across_sessions(self):
        self.client.post(reverse("review_weekly_phase", args=["creative"]), {"finish": "1"})
        self.client.get(reverse("review_weekly_start"))
        session2 = ReviewSession.objects.filter(cadence="weekly", completed_at__isnull=True).get()
        session2.phase_state = {"phase": "creative"}
        session2.save()
        self.client.post(reverse("review_weekly_phase", args=["creative"]), {"finish": "1"})
        session2.refresh_from_db()
        self.assertEqual(session2.stats_snapshot["streak"], 2)


class MonthlyAndSimpleWizardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_monthly_wizard_resume_and_finish(self):
        response = self.client.get(reverse("review_monthly_start"))
        self.assertRedirects(response, reverse("review_monthly_phase", args=["areas"]))
        self.client.post(reverse("review_monthly_phase", args=["areas"]), {"next": "1"})
        self.client.post(reverse("review_monthly_phase", args=["someday"]), {"next": "1"})
        response = self.client.post(reverse("review_monthly_phase", args=["carryover"]), {"finish": "1"})
        session = ReviewSession.objects.get(cadence="monthly")
        self.assertIsNotNone(session.completed_at)
        self.assertContains(response, "1")

    def test_quarterly_checklist_finish(self):
        self.client.get(reverse("review_simple_start", args=["quarterly"]))
        response = self.client.post(reverse("review_simple_phase", args=["quarterly", "checklist"]), {"finish": "1"})
        session = ReviewSession.objects.get(cadence="quarterly")
        self.assertIsNotNone(session.completed_at)
        self.assertContains(response, "1")

    def test_yearly_checklist_capture(self):
        self.client.get(reverse("review_simple_start", args=["yearly"]))
        self.client.post(reverse("review_simple_phase", args=["yearly", "checklist"]), {"capture": "Big vision idea"})
        self.assertEqual(InboxItem.objects.filter(source="review").count(), 1)


class TrustStripAndTodayBannerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_never_reviewed_shows_never(self):
        response = self.client.get(reverse("today"))
        self.assertContains(response, "review never")

    def test_overdue_review_shows_red_banner_on_today(self):
        # timedelta(days=12) at time-of-day X can land on a 12- or 13-day-old
        # *date* depending on the clock when the test runs (date subtraction,
        # not exact 24h periods) - go safely past the >10 threshold instead
        # of asserting an exact day count.
        ReviewSession.objects.create(
            cadence="weekly", completed_at=timezone.now() - timedelta(days=15)
        )
        response = self.client.get(reverse("today"))
        self.assertContains(response, "Your system is only trusted if it's current.")

    def test_recent_review_does_not_show_banner(self):
        ReviewSession.objects.create(cadence="weekly", completed_at=timezone.now() - timedelta(days=2))
        response = self.client.get(reverse("today"))
        self.assertNotContains(response, "Your system is only trusted")


class ReviewScreenSmokeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_dashboard_and_all_wizard_entry_points_render(self):
        response = self.client.get(reverse("review_dashboard"))
        self.assertEqual(response.status_code, 200)
        for name in ("review_weekly_start", "review_monthly_start"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
        for cadence in ("quarterly", "yearly"):
            response = self.client.get(reverse("review_simple_start", args=[cadence]))
            self.assertEqual(response.status_code, 302)

    def test_every_weekly_phase_renders(self):
        Task.objects.create(title="A project", is_project=True)
        for phase in WEEKLY_PHASES:
            session = ReviewSession.objects.filter(cadence="weekly", completed_at__isnull=True).first()
            if not session:
                self.client.get(reverse("review_weekly_start"))
                session = ReviewSession.objects.get(cadence="weekly")
            session.phase_state = {"phase": phase}
            session.save()
            response = self.client.get(reverse("review_weekly_phase", args=[phase]))
            self.assertEqual(response.status_code, 200, phase)


ntfy_settings = override_settings(NTFY_TOPIC="test-topic-xyz")


@ntfy_settings
class NotifyHelperTests(TestCase):
    def test_noop_without_ntfy_topic(self):
        with override_settings(NTFY_TOPIC=""), patch("core.notifications.requests.post") as mock_post:
            sent = notify("missed_block", "Title", "Message")
            self.assertFalse(sent)
            mock_post.assert_not_called()

    @patch("core.notifications.requests.post")
    def test_sends_when_configured(self, mock_post):
        sent = notify("missed_block", "Title", "Message", ref_id=1)
        self.assertTrue(sent)
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.args[0], "https://ntfy.sh/test-topic-xyz")
        self.assertEqual(NotificationLog.objects.filter(kind="missed_block", ref_id=1).count(), 1)

    @patch("core.notifications.requests.post")
    def test_dedupe_same_kind_and_ref_same_day(self, mock_post):
        notify("missed_block", "Title", "Message", ref_id=5)
        sent_again = notify("missed_block", "Title", "Message", ref_id=5)
        self.assertFalse(sent_again)
        mock_post.assert_called_once()

    @patch("core.notifications.requests.post")
    def test_different_ref_id_not_deduped(self, mock_post):
        notify("missed_block", "Title", "Message", ref_id=1)
        sent = notify("missed_block", "Title", "Message", ref_id=2)
        self.assertTrue(sent)
        self.assertEqual(mock_post.call_count, 2)

    @patch("core.notifications.requests.post")
    def test_force_bypasses_dedupe(self, mock_post):
        notify("missed_block", "Title", "Message", ref_id=1)
        sent_again = notify("missed_block", "Title", "Message", ref_id=1, force=True)
        self.assertTrue(sent_again)
        self.assertEqual(mock_post.call_count, 2)

    @patch("core.notifications.requests.post")
    def test_disabled_kind_is_a_noop(self, mock_post):
        NotificationSetting.objects.create(kind="missed_block", enabled=False)
        sent = notify("missed_block", "Title", "Message")
        self.assertFalse(sent)
        mock_post.assert_not_called()

    @patch("core.notifications.requests.post")
    def test_kind_with_no_setting_row_defaults_enabled(self, mock_post):
        sent = notify("missed_block", "Title", "Message")
        self.assertTrue(sent)


class NotificationSettingsPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_settings_page_lists_all_kinds(self):
        response = self.client.get(reverse("settings"))
        for kind in KINDS:
            self.assertContains(response, kind)

    def test_toggle_flips_state(self):
        self.client.post(reverse("notification_toggle", args=["missed_block"]))
        self.assertFalse(is_kind_enabled("missed_block"))
        self.client.post(reverse("notification_toggle", args=["missed_block"]))
        self.assertTrue(is_kind_enabled("missed_block"))

    @ntfy_settings
    @patch("core.notifications.requests.post")
    def test_test_fire_sends_regardless_of_toggle_state(self, mock_post):
        NotificationSetting.objects.create(kind="missed_block", enabled=False)
        response = self.client.post(reverse("notification_test_fire", args=["missed_block"]))
        mock_post.assert_called_once()
        self.assertContains(response, "Sent")

    def test_test_fire_reports_not_sent_when_unconfigured(self):
        with override_settings(NTFY_TOPIC=""):
            response = self.client.post(reverse("notification_test_fire", args=["missed_block"]))
            self.assertContains(response, "Not sent")


@ntfy_settings
class MissedBlockNotifyTests(TestCase):
    @patch("core.notifications.requests.post")
    def test_detect_missed_blocks_sends_notification(self, mock_post):
        task = Task.objects.create(title="Gym")
        TimeBlock.objects.create(
            task=task, start=timezone.now() - timedelta(hours=2), end=timezone.now() - timedelta(hours=1)
        )
        call_command("detect_missed_blocks")
        mock_post.assert_called_once()
        self.assertTrue(NotificationLog.objects.filter(kind="missed_block").exists())


@ntfy_settings
class ReviewReminderCommandTests(TestCase):
    def setUp(self):
        # A Friday (matches default weekday=4) at 15:45 - 15 minutes before
        # the default 16:00 scheduled time.
        self.config = ReviewConfig.objects.create(cadence="weekly", weekday=4, duration_min=60)

    @patch("core.notifications.requests.post")
    def test_sends_within_15min_window(self, mock_post):
        call_command("notify_review_reminders", "--now", "2026-07-17T15:50:00+06:00")  # Friday
        mock_post.assert_called_once()
        self.assertTrue(NotificationLog.objects.filter(kind="review_reminder", ref_id=self.config.id).exists())

    @patch("core.notifications.requests.post")
    def test_does_not_send_outside_window(self, mock_post):
        call_command("notify_review_reminders", "--now", "2026-07-17T10:00:00+06:00")
        mock_post.assert_not_called()

    @patch("core.notifications.requests.post")
    def test_dedupes_across_multiple_runs_same_day(self, mock_post):
        call_command("notify_review_reminders", "--now", "2026-07-17T15:50:00+06:00")
        call_command("notify_review_reminders", "--now", "2026-07-17T15:55:00+06:00")
        mock_post.assert_called_once()

    @patch("core.notifications.requests.post")
    def test_wrong_weekday_does_not_send(self, mock_post):
        call_command("notify_review_reminders", "--now", "2026-07-16T15:50:00+06:00")  # Thursday
        mock_post.assert_not_called()


@ntfy_settings
class ReviewOverdueCommandTests(TestCase):
    @patch("core.notifications.requests.post")
    def test_never_reviewed_sends_overdue_nag(self, mock_post):
        ReviewConfig.objects.create(cadence="weekly")
        call_command("notify_review_overdue")
        mock_post.assert_called_once()

    @patch("core.notifications.requests.post")
    def test_recently_reviewed_does_not_nag(self, mock_post):
        ReviewConfig.objects.create(cadence="weekly")
        ReviewSession.objects.create(cadence="weekly", completed_at=timezone.now() - timedelta(days=1))
        call_command("notify_review_overdue")
        mock_post.assert_not_called()

    @patch("core.notifications.requests.post")
    def test_unconfigured_cadence_skipped(self, mock_post):
        call_command("notify_review_overdue")
        mock_post.assert_not_called()


@ntfy_settings
class FollowUpDigestTests(TestCase):
    @patch("core.notifications.requests.post")
    def test_batches_all_overdue_into_one_notification(self, mock_post):
        for i in range(3):
            Task.objects.create(
                title=f"W{i}", list=Task.List.WAITING, waiting_since=date.today() - timedelta(days=10)
            )
        call_command("notify_follow_up_digest")
        mock_post.assert_called_once()
        message = mock_post.call_args.kwargs["data"].decode()
        self.assertIn("3", message)

    @patch("core.notifications.requests.post")
    def test_no_overdue_no_notification(self, mock_post):
        call_command("notify_follow_up_digest")
        mock_post.assert_not_called()


@ntfy_settings
class RecurringOverdueCommandTests(TestCase):
    @patch("core.notifications.requests.post")
    def test_counts_overdue_recurring_instances(self, mock_post):
        template = RecurringTemplate.objects.create(title="Standup", rrule="FREQ=DAILY")
        for i in range(2):
            Task.objects.create(
                title="Standup", recurring_template=template, occurrence_date=date.today() - timedelta(days=i + 1)
            )
        call_command("notify_recurring_overdue")
        mock_post.assert_called_once()
        message = mock_post.call_args.kwargs["data"].decode()
        self.assertIn("2", message)

    @patch("core.notifications.requests.post")
    def test_no_overdue_instances_no_notification(self, mock_post):
        call_command("notify_recurring_overdue")
        mock_post.assert_not_called()


class StatsAggregateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")
        self.today = timezone.localtime().date()

    def test_stats_page_renders_empty(self):
        response = self.client.get(reverse("stats"))
        self.assertEqual(response.status_code, 200)

    def test_completions_per_day_counts_by_completion_date(self):
        def completed_at(days_ago):
            return timezone.now() - timedelta(days=days_ago)

        Task.objects.create(title="A", completed_at=completed_at(0))
        Task.objects.create(title="B", completed_at=completed_at(0))
        Task.objects.create(title="C", completed_at=completed_at(5))
        response = self.client.get(reverse("stats"))
        data = json.loads(response.context["completions_per_day_json"])
        today_label = self.today.strftime("%d %b")
        five_days_ago_label = (self.today - timedelta(days=5)).strftime("%d %b")
        by_label = {d["label"]: d["count"] for d in data}
        self.assertEqual(by_label[today_label], 2)
        self.assertEqual(by_label[five_days_ago_label], 1)
        self.assertEqual(len(data), 30)

    def test_completions_per_week_groups_by_monday(self):
        this_monday = self.today - timedelta(days=self.today.weekday())
        Task.objects.create(title="A", completed_at=timezone.now())
        Task.objects.create(title="B", completed_at=timezone.now() - timedelta(weeks=3))
        response = self.client.get(reverse("stats"))
        data = json.loads(response.context["completions_per_week_json"])
        self.assertEqual(len(data), 12)
        self.assertEqual(data[-1]["label"], this_monday.strftime("%d %b"))
        self.assertEqual(data[-1]["count"], 1)

    def test_review_streaks_and_last_completed(self):
        ReviewSession.objects.create(cadence="weekly", completed_at=timezone.now() - timedelta(days=7))
        ReviewSession.objects.create(cadence="weekly", completed_at=timezone.now())
        response = self.client.get(reverse("stats"))
        weekly_row = next(r for r in response.context["review_rows"] if r["cadence"] == "Weekly")
        self.assertEqual(weekly_row["streak"], 2)
        self.assertIsNotNone(weekly_row["last_completed"])

    def test_inbox_zero_event_count(self):
        from core.stats import _inbox_zero_event_count

        now = timezone.now()
        # created_at is auto_now_add, so the ORM silently forces it to "now"
        # on .create() regardless of any explicit kwarg - build the rows first,
        # then overwrite created_at with a direct .update() (which bypasses
        # auto_now_add's save()-time override) to backdate them.
        a = InboxItem.objects.create(title="A", processed_at=now - timedelta(hours=2))
        b = InboxItem.objects.create(title="B", processed_at=now - timedelta(minutes=30))
        c = InboxItem.objects.create(title="C", processed_at=now - timedelta(minutes=20))
        # Item A created and processed alone -> inbox goes 1 -> 0 (one zero event).
        InboxItem.objects.filter(pk=a.pk).update(created_at=now - timedelta(hours=3))
        # B and C created while A is still open, processed together later ->
        # inbox goes 0->1->2->1->0 (a second zero event).
        InboxItem.objects.filter(pk=b.pk).update(created_at=now - timedelta(hours=1, minutes=50))
        InboxItem.objects.filter(pk=c.pk).update(created_at=now - timedelta(hours=1, minutes=40))
        self.assertEqual(_inbox_zero_event_count(), 2)

    def test_missed_block_rate_excludes_scheduled(self):
        task = Task.objects.create(title="A")
        now = timezone.now()
        TimeBlock.objects.create(task=task, start=now, end=now + timedelta(hours=1), status=TimeBlock.Status.MISSED)
        TimeBlock.objects.create(
            task=task, start=now, end=now + timedelta(hours=1), status=TimeBlock.Status.COMPLETED
        )
        TimeBlock.objects.create(
            task=task, start=now, end=now + timedelta(hours=1), status=TimeBlock.Status.SCHEDULED
        )
        response = self.client.get(reverse("stats"))
        self.assertEqual(response.context["missed_block_rate"], 50)

    def test_missed_block_rate_none_when_no_data(self):
        response = self.client.get(reverse("stats"))
        self.assertIsNone(response.context["missed_block_rate"])

    def test_median_latency_label(self):
        now = timezone.now()
        InboxItem.objects.create(title="A", processed_at=now)
        InboxItem.objects.filter(title="A").update(created_at=now - timedelta(minutes=10))
        response = self.client.get(reverse("stats"))
        self.assertEqual(response.context["median_latency_label"], "10m")

    def test_median_latency_dash_when_nothing_processed(self):
        response = self.client.get(reverse("stats"))
        self.assertEqual(response.context["median_latency_label"], "—")

    def test_two_minute_rule_count(self):
        InboxItem.objects.create(title="A", done_directly=True, processed_at=timezone.now())
        InboxItem.objects.create(title="B", done_directly=True, processed_at=timezone.now())
        InboxItem.objects.create(title="C", done_directly=False)
        response = self.client.get(reverse("stats"))
        self.assertEqual(response.context["two_minute_count"], 2)


@override_settings(MEDIA_ROOT=_MEDIA_TMPDIR)
class PrivateAttachmentServingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.note = Note.objects.create(title="Doc", body="")
        self.client.post(
            reverse("note_attachment_upload", args=[self.note.id]),
            {"file": SimpleUploadedFile("report.pdf", b"pdf-bytes")},
        )
        self.attachment = self.note.attachments.get()

    @override_settings(DEBUG=True)
    def test_dev_mode_streams_file_directly(self):
        # Django's test runner forces settings.DEBUG=False for every test
        # (setup_test_environment()), regardless of the project's real .env -
        # so exercising the dev-mode branch here needs an explicit override.
        response = self.client.get(reverse("note_attachment_download", args=[self.note.id, self.attachment.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"pdf-bytes")
        self.assertNotIn("X-Accel-Redirect", response)

    @override_settings(DEBUG=False)
    def test_prod_mode_uses_x_accel_redirect(self):
        response = self.client.get(reverse("note_attachment_download", args=[self.note.id, self.attachment.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Accel-Redirect", response)
        self.assertTrue(response["X-Accel-Redirect"].startswith("/protected-media/"))
        self.assertEqual(response.content, b"")  # nginx serves the body, not Django

    def test_content_disposition_uses_original_filename(self):
        response = self.client.get(reverse("note_attachment_download", args=[self.note.id, self.attachment.id]))
        self.assertIn("report.pdf", response["Content-Disposition"])

    def test_missing_attachment_404s(self):
        response = self.client.get(reverse("note_attachment_download", args=[self.note.id, 99999]))
        self.assertEqual(response.status_code, 404)


class BackupDatabaseCommandTests(TestCase):
    def test_noop_without_bucket_configured(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BACKUP_S3_BUCKET", None)
            call_command("backup_database")  # should not raise, just skip

    @patch("boto3.client")
    @patch("core.management.commands.backup_database.subprocess.run")
    def test_runs_pg_dump_and_uploads_and_prunes(self, mock_run, mock_boto_client):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        old_time = timezone.now() - timedelta(days=20)
        recent_time = timezone.now() - timedelta(days=1)
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "gtd-backups/old.dump", "LastModified": old_time},
                    {"Key": "gtd-backups/recent.dump", "LastModified": recent_time},
                ]
            }
        ]
        mock_s3.get_paginator.return_value = mock_paginator

        with patch.dict(os.environ, {"BACKUP_S3_BUCKET": "my-bucket"}):
            call_command("backup_database")

        mock_run.assert_called_once()
        pg_dump_cmd = mock_run.call_args.args[0]
        self.assertEqual(pg_dump_cmd[0], "pg_dump")
        mock_s3.upload_file.assert_called_once()
        mock_s3.delete_object.assert_called_once_with(Bucket="my-bucket", Key="gtd-backups/old.dump")

    @patch("core.management.commands.backup_database.subprocess.run")
    def test_pg_dump_failure_raises_with_event_id(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="connection refused")
        with patch.dict(os.environ, {"BACKUP_S3_BUCKET": "my-bucket"}):
            with self.assertRaises(Exception) as ctx:
                call_command("backup_database")
        self.assertIn("event_id", str(ctx.exception))


class SyncErrorLoggingTests(TestCase):
    @gcal_settings
    @patch("core.google_calendar.GoogleCalendarClient.list_events")
    def test_non_410_sync_error_is_logged_and_reraised(self, mock_list_events):
        from googleapiclient.errors import HttpError

        from core.google_calendar import sync_calendar

        credential = GoogleCredential.objects.create(refresh_token=b"x", gtd_calendar_id="cal1")
        error_resp = MagicMock(status=500)
        mock_list_events.side_effect = HttpError(error_resp, b"Server error")

        with self.assertLogs("core.google_calendar", level="ERROR") as log_ctx:
            with self.assertRaises(HttpError):
                sync_calendar(credential)
        self.assertIn("event_id", log_ctx.output[0])
