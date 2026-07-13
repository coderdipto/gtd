// Alpine component powering the @context/#tag typeahead on free-text
// description/body fields in the clarify wizard (core/tagging.py owns the
// actual parsing regex server-side; this only needs to *suggest* existing
// tag names, so a loose client-side mirror of that regex is fine here).
function tagTypeahead(allTags) {
  return {
    allTags: (allTags || []).map((t) => ({ name: t.name, prefix: t.is_context ? "@" : "#" })),
    suggestions: [],
    open: false,
    activeIndex: 0,
    tokenStart: null,
    onInput(e) {
      const el = e.target;
      const pos = el.selectionStart;
      const upToCaret = el.value.slice(0, pos);
      const match = upToCaret.match(/(?:^|\s)([@#])([a-z0-9-]*)$/i);
      if (!match) {
        this.open = false;
        return;
      }
      const prefix = match[1];
      const partial = match[2].toLowerCase();
      this.tokenStart = pos - partial.length - 1;
      this.suggestions = this.allTags
        .filter((t) => t.prefix === prefix && t.name.startsWith(partial) && t.name !== partial)
        .slice(0, 6);
      this.activeIndex = 0;
      this.open = this.suggestions.length > 0;
    },
    select(s) {
      const el = this.$refs.input;
      const before = el.value.slice(0, this.tokenStart);
      const after = el.value.slice(el.selectionStart);
      const inserted = s.prefix + s.name + " ";
      el.value = before + inserted + after;
      const newPos = (before + inserted).length;
      this.open = false;
      this.$nextTick(() => {
        el.focus();
        el.setSelectionRange(newPos, newPos);
      });
    },
    onKeydown(e) {
      if (!this.open) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        this.activeIndex = (this.activeIndex + 1) % this.suggestions.length;
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        this.activeIndex = (this.activeIndex - 1 + this.suggestions.length) % this.suggestions.length;
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        this.select(this.suggestions[this.activeIndex]);
      } else if (e.key === "Escape") {
        // Stop this from bubbling to the focus-card's window-level Escape
        // handler (which navigates back to the Inbox) - here it should
        // just close the suggestion dropdown.
        e.stopPropagation();
        this.open = false;
      }
    },
  };
}
