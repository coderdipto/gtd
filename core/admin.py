from django.contrib import admin
from unfold.admin import ModelAdmin

from . import models

# Unfold only styles form widgets it renders itself (unfold.admin.ModelAdmin)
# - registering with plain admin.ModelAdmin gets Unfold's page chrome but
# leaves every field an unstyled, borderless, background-less <input>
# (Tailwind's preflight strips the browser default border, same class of
# gotcha as TEXT_INPUT_CLASS in core/forms.py) - invisible in dark mode.
admin.site.register(models.Tag, ModelAdmin)
admin.site.register(models.Area, ModelAdmin)
admin.site.register(models.InboxItem, ModelAdmin)
admin.site.register(models.Task, ModelAdmin)
admin.site.register(models.Note, ModelAdmin)
admin.site.register(models.NoteAttachment, ModelAdmin)
admin.site.register(models.RecurringTemplate, ModelAdmin)
admin.site.register(models.TimeBlock, ModelAdmin)
admin.site.register(models.GoogleCredential, ModelAdmin)
admin.site.register(models.SyncChannel, ModelAdmin)
admin.site.register(models.ReviewConfig, ModelAdmin)
admin.site.register(models.ReviewSession, ModelAdmin)
admin.site.register(models.CaptureToken, ModelAdmin)
admin.site.register(models.NotificationLog, ModelAdmin)
