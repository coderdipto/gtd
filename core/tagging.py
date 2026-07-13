import re

# @word = context, #word = plain tag. Tokens stay in the source text; the
# resulting Tag objects are synced additively onto the target's M2M on every
# save (see solution-plan.md Step 4 "Inline tag parser").
#
# solution-plan.md's own regex spec (@([a-z0-9\-]+) / #([a-z0-9\-]+)) has no
# boundary condition, which would tag email addresses ("john@example.com" ->
# context "example") and URL fragments ("...#comment" -> tag "comment"). This
# requires the prefix to be at the start of the text or preceded by
# whitespace, closing that gap - a deliberate deviation from the plan's
# literal (underspecified) regex, not an oversight.
TAG_RE = re.compile(r"(?:^|(?<=\s))(?P<prefix>[@#])(?P<name>[a-z0-9\-]+)", re.IGNORECASE)


def extract_tags(text):
    """Yields (name, is_context) for every @word/#word token in text, case-folded."""
    if not text:
        return
    for match in TAG_RE.finditer(text):
        yield match.group("name").lower(), match.group("prefix") == "@"


def sync_tags_from_text(obj, *texts):
    """Get-or-create a Tag for every @/# token across texts and additively
    attach it to obj.tags. Never removes existing tags."""
    from .models import Tag

    seen = {}
    for text in texts:
        for name, is_context in extract_tags(text):
            seen.setdefault(name, is_context)
    for name, is_context in seen.items():
        tag, _ = Tag.objects.get_or_create(name=name, defaults={"is_context": is_context})
        obj.tags.add(tag)
