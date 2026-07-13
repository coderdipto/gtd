from django import forms

from .models import InboxItem


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
                        "focus:border-water focus:outline-none focus-visible:ring-0 py-2"
                    ),
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 2,
                    "placeholder": "Details (optional)",
                    "class": (
                        "w-full text-sm bg-transparent border border-line rounded-md p-2 "
                        "focus:border-water focus:outline-none"
                    ),
                }
            ),
        }
