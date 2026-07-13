from django import forms

from .models import InboxItem, Note, Task

TEXT_INPUT_CLASS = (
    "w-full text-sm border border-line rounded-md p-2 focus:border-water focus:outline-none "
    "focus-visible:ring-2 ring-water"
)
TEXTAREA_CLASS = TEXT_INPUT_CLASS
SELECT_CLASS = TEXT_INPUT_CLASS

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
                        "w-full text-xl bg-transparent border-0 border-b border-line "
                        "focus:border-water focus:outline-none focus-visible:ring-2 ring-water py-2"
                    ),
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 2,
                    "placeholder": "Details (optional)",
                    "class": (
                        "w-full text-sm bg-transparent border border-line rounded-md p-2 "
                        "focus:border-water focus:outline-none focus-visible:ring-2 ring-water"
                    ),
                }
            ),
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
        fields = ["title", "body"]
        widgets = {
            "title": forms.TextInput(attrs={"class": TEXT_INPUT_CLASS, "autofocus": True}),
            "body": forms.Textarea(attrs={"class": TEXTAREA_CLASS, "rows": 5, **TAG_FIELD_ATTRS}),
        }


class SingleActionForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title", "description", "horizon", "due_date", "area"]
        widgets = {
            "title": forms.TextInput(attrs={"class": TEXT_INPUT_CLASS, "autofocus": True}),
            "description": forms.Textarea(
                attrs={"class": TEXTAREA_CLASS, "rows": 3, "placeholder": "@context #tag", **TAG_FIELD_ATTRS}
            ),
            "horizon": forms.Select(attrs={"class": SELECT_CLASS}),
            "due_date": forms.DateInput(attrs={"class": TEXT_INPUT_CLASS, "type": "date"}),
            "area": forms.Select(attrs={"class": SELECT_CLASS}),
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
