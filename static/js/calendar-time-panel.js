// Drag-to-create mini FullCalendar shared by project_detail.html and
// task_detail.html (components/calendar_time_panel.html). A persistent
// <script src> file, loaded once in base.html's <head> - not an inline
// <script> inside the partial itself, same reasoning as sortable-lists.js:
// <body hx-boost="true"> means normal navigation never re-fires
// DOMContentLoaded, so boosted/swapped-in content is (re-)initialized via
// htmx:load instead, which fires once for the initial page and again for
// every swap.
//
// An earlier version put this init logic inline in the partial's own
// <script> tag. That re-executed on every boosted visit to a detail page,
// permanently stacking a new document-level htmx:load listener each time -
// and because listeners fire in registration order, the *oldest* listener
// (with that visit's events JSON frozen in its own closure) could still win
// the "already initialized" race and block a newer, correctly-updated
// listener from ever running. Symptom: a newly created block always saved
// correctly (the server-rendered text list next to the calendar proved
// that), but never appeared on the calendar grid itself after the first
// page load in a session. Reading events fresh from a data-* attribute
// every time this single, persistent listener fires - rather than baking
// them into a per-visit script closure - removes the possibility of stale
// data entirely.
document.body.addEventListener("htmx:load", (evt) => {
  const root = evt.detail.elt;
  const el = root.matches?.("#fc-mini-calendar") ? root : root.querySelector?.("#fc-mini-calendar");
  if (!el) return;

  const form = document.getElementById("add-block-form");
  const startInput = form.querySelector('[name="start"]');
  const endInput = form.querySelector('[name="end"]');

  function toLocalValue(date) {
    const pad = (n) => String(n).padStart(2, "0");
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate())
      + "T" + pad(date.getHours()) + ":" + pad(date.getMinutes());
  }

  if (el._fcCalendar) el._fcCalendar.destroy();

  const calendar = new FullCalendar.Calendar(el, {
    initialView: "timeGridWeek",
    headerToolbar: { left: "prev,next today", center: "title", right: "" },
    slotMinTime: "06:00:00",
    slotMaxTime: "22:00:00",
    height: 420,
    selectable: true,
    selectMirror: true,
    unselectAuto: false,
    displayEventTime: false,
    events: JSON.parse(el.dataset.events),
    select(info) {
      startInput.value = toLocalValue(info.start);
      endInput.value = toLocalValue(info.end);
      // requestSubmit(), not submit(): the latter bypasses the DOM
      // "submit" event entirely (a real browser quirk), which is what
      // <body hx-boost="true"> listens for to AJAX-intercept the form -
      // form.submit() would fall through to a real full-page POST instead
      // of htmx's boosted redirect-follow.
      form.requestSubmit();
    },
  });
  calendar.render();
  el._fcCalendar = calendar;
});
