from django.contrib import admin

from . import models

admin.site.register(models.Tag)
admin.site.register(models.Area)
admin.site.register(models.InboxItem)
admin.site.register(models.Task)
admin.site.register(models.Note)
admin.site.register(models.NoteAttachment)
admin.site.register(models.RecurringTemplate)
admin.site.register(models.TimeBlock)
admin.site.register(models.GoogleCredential)
admin.site.register(models.SyncChannel)
admin.site.register(models.ReviewConfig)
admin.site.register(models.ReviewSession)
admin.site.register(models.CaptureToken)
admin.site.register(models.NotificationLog)
