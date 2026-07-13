from django.contrib.postgres.search import SearchVector
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Note


@receiver(post_save, sender=Note)
def update_note_search_vector(sender, instance, **kwargs):
    # .update() rather than instance.save() so this doesn't re-trigger
    # post_save (which would recurse) and doesn't touch updated_at again.
    Note.objects.filter(pk=instance.pk).update(search=SearchVector("title", "body"))
