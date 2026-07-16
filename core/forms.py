from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import Area, InboxItem, Note, Task

TEXT_INPUT_CLASS = (
    "w-full text-sm bg-surface text-ink border border-line rounded-md p-2 "
    "focus:border-water focus:outline-none"
)
TEXTAREA_CLASS = TEXT_INPUT_CLASS
SELECT_CLASS = TEXT_INPUT_CLASS


class StyledAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"class": TEXT_INPUT_CLASS, "autofocus": True})
        self.fields["password"].widget.attrs.update({"class": TEXT_INPUT_CLASS})

# Merged into a Textarea's attrs to wire it up to the Alpine tagTypeahead
# component (static/js/tag-typeahead.js) via core/partials/field_tagged.html.
TAG_FIELD_ATTRS = {
    "x-ref": "input",
    "@input": "onInput($event)",
    "@keydown": "onKeydown($event)",
}


class InboxItemForm(forms.ModelForm):
    class Meta:
        model = InboxItem
        fields = ["title", "description"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "placeholder": "What's on your mind?",
                    "autofocus": True,
                    "autocomplete": "off",
                    "x-ref": "title",
                    "class": (
                        "w-full text-xl bg-transparent border-0 rounded-md px-3 py-2.5 "
                        "focus:outline-none"
                    ),
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 2,
                    "placeholder": "Details (optional)",
                    "class": (
                        "w-full text-sm bg-transparent border border-line rounded-md p-3 "
                        "focus:border-water focus:outline-none"
                    ),
                }
            ),
        }


class AreaForm(forms.ModelForm):
    class Meta:
        model = Area
        fields = ["name", "description"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": TEXT_INPUT_CLASS, "autofocus": True, "placeholder": "e.g. Health, Family, Career"}
            ),
            "description": forms.Textarea(attrs={"class": TEXTAREA_CLASS, "rows": 2, "placeholder": "Optional"}),
        }


class SomedayForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title", "description", "area"]
        widgets = {
            "title": forms.TextInput(attrs={"class": TEXT_INPUT_CLASS, "autofocus": True}),
            "description": forms.Textarea(attrs={"class": TEXTAREA_CLASS, "rows": 3, **TAG_FIELD_ATTRS}),
            "area": forms.Select(attrs={"class": SELECT_CLASS}),
        }


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ["title", "body", "linked_project"]
        widgets = {
            "title": forms.TextInput(attrs={"class": TEXT_INPUT_CLASS, "autofocus": True}),
            "body": forms.Textarea(attrs={"class": TEXTAREA_CLASS, "rows": 5, **TAG_FIELD_ATTRS}),
            "linked_project": forms.Select(attrs={"class": SELECT_CLASS}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only offer active (not completed/trashed) projects to link to; the
        # blank choice keeps the link optional (task #19).
        self.fields["linked_project"].queryset = Task.objects.filter(
            is_project=True, completed_at__isnull=True
        ).exclude(list=Task.List.TRASH).order_by("title")
        self.fields["linked_project"].required = False
        self.fields["linked_project"].label = "Linked project"
        self.fields["linked_project"].empty_label = "— none —"


class SingleActionForm(forms.ModelForm):
    class Meta:
        model = Task
        # energy/estimate_min (task #16) are optional Engage facets — included
        # here so task detail can edit them, but the clarify Single screen's
        # template only renders the core fields, keeping capture lean.
        fields = ["title", "description", "horizon", "due_date", "area", "energy", "estimate_min"]
        widgets = {
            "title": forms.TextInput(attrs={"class": TEXT_INPUT_CLASS, "autofocus": True}),
            "description": forms.Textarea(
                attrs={"class": TEXTAREA_CLASS, "rows": 3, "placeholder": "@context #tag", **TAG_FIELD_ATTRS}
            ),
            "horizon": forms.Select(attrs={"class": SELECT_CLASS}),
            "due_date": forms.DateInput(attrs={"class": TEXT_INPUT_CLASS, "type": "date"}),
            "area": forms.Select(attrs={"class": SELECT_CLASS}),
            "energy": forms.Select(attrs={"class": SELECT_CLASS}),
            "estimate_min": forms.NumberInput(attrs={"class": TEXT_INPUT_CLASS, "min": 0, "placeholder": "e.g. 15"}),
        }


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title", "description", "area"]
        widgets = {
            "title": forms.TextInput(attrs={"class": TEXT_INPUT_CLASS, "autofocus": True}),
            "description": forms.Textarea(
                attrs={"class": TEXTAREA_CLASS, "rows": 3, "placeholder": "@context #tag", **TAG_FIELD_ATTRS}
            ),
            "area": forms.Select(attrs={"class": SELECT_CLASS}),
        }


class DelegateForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title", "description", "waiting_on", "follow_up_after_days"]
        widgets = {
            "title": forms.TextInput(attrs={"class": TEXT_INPUT_CLASS, "autofocus": True}),
            "description": forms.Textarea(attrs={"class": TEXTAREA_CLASS, "rows": 2, **TAG_FIELD_ATTRS}),
            "waiting_on": forms.TextInput(
                attrs={"class": TEXT_INPUT_CLASS, "placeholder": "Who / what are you waiting on?"}
            ),
            "follow_up_after_days": forms.NumberInput(attrs={"class": TEXT_INPUT_CLASS}),
        }
