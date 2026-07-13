// Rotating dismissible "GTD tip" strip (docs/design.md §9, Today footer).
// docs/solution-plan.md attributes this copy to a source study doc
// ("gtd-detailed-study.md" §8.1) that isn't actually present anywhere in
// this repo, so these are generic, well-known GTD pitfalls written from
// scratch rather than a verbatim quote from a document that doesn't exist
// here - see docs/task-breakdown.md Epic 9 for the flag on this gap.
const GTD_TIPS = [
  "A next action has to be physical and visible - \"call\", \"draft\", \"buy\", not \"figure out\".",
  "Someday/Maybe isn't a graveyard. If you never review it, it might as well be a trash can.",
  "The inbox is a waiting room, not storage. Anything that sits there un-clarified erodes trust in the system.",
  "Weekly review is the glue - skip it a few times and the whole system quietly stops being trustworthy.",
  "\"I'll remember it\" is exactly the plan GTD exists to replace.",
  "A stalled project isn't a failure, it's just missing its next action. Add one and move on.",
  "Big-3 stars are a spotlight, not a to-do list — pick what actually matters this week, not everything urgent.",
  "Contexts should describe where/how you can act (@calls, @errands), not just be more tags.",
];

function gtdTipStrip() {
  return {
    tip: "",
    visible: true,
    init() {
      const today = new Date().toISOString().slice(0, 10);
      const dismissedOn = localStorage.getItem("gtdTipDismissedOn");
      if (dismissedOn === today) {
        this.visible = false;
        return;
      }
      const dayOfYear = Math.floor(
        (new Date() - new Date(new Date().getFullYear(), 0, 0)) / 86400000
      );
      this.tip = GTD_TIPS[dayOfYear % GTD_TIPS.length];
    },
    dismiss() {
      localStorage.setItem("gtdTipDismissedOn", new Date().toISOString().slice(0, 10));
      this.visible = false;
    },
  };
}
