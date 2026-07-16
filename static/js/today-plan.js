// Today "Plan on calendar" panel (task #17). A tiny init file loaded once
// globally from base.html (like calendar-time-panel.js) — it registers no
// listeners and only defines window.initTodayPlan, which the Alpine panel calls
// the first time it's opened. The heavy FullCalendar library is lazy-loaded on
// that first open (same on-demand approach as sortable-lists.js), so pages that
// never open the panel — and the Today page until the user opens it — never
// fetch it. Config (event source + endpoint URL templates) is read from data
// attributes, since a static JS file can't use {% url %}.
(function () {
  var FC_SRC = "https://cdn.jsdelivr.net/npm/fullcalendar@6.1.15/index.global.min.js";
  var fcPromise = null;

  function loadFullCalendar() {
    if (window.FullCalendar) return Promise.resolve();
    if (fcPromise) return fcPromise;
    fcPromise = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = FC_SRC;
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error("failed to load FullCalendar")); };
      document.head.appendChild(s);
    });
    return fcPromise;
  }

  window.initTodayPlan = function (root) {
    var el = root.querySelector("#today-plan-calendar");
    if (!el || el.dataset.init) return;
    el.dataset.init = "1";
    var eventsUrl = el.dataset.eventsUrl;
    var createTpl = el.dataset.createUrlTemplate; // .../tasks/0/blocks/
    var updateTpl = el.dataset.updateUrlTemplate; // .../blocks/0/

    loadFullCalendar().then(function () {
      var sources = root.querySelector("#today-plan-sources");
      if (sources) {
        new FullCalendar.Draggable(sources, {
          itemSelector: ".plan-chip",
          eventData: function (chip) {
            // Use the task's own time estimate (task #16) as the block length
            // when it has one, so a 15-minute task drops as a 15-minute block;
            // otherwise fall back to a 1-hour default.
            var est = parseInt(chip.dataset.estimate, 10);
            return {
              title: chip.dataset.title,
              duration: est > 0 ? { minutes: est } : "01:00",
              extendedProps: { taskId: chip.dataset.taskId },
            };
          },
        });
      }

      var calendar = new FullCalendar.Calendar(el, {
        initialView: "timeGridDay",
        headerToolbar: { left: "prev,next today", center: "title", right: "" },
        slotMinTime: "06:00:00",
        slotMaxTime: "22:00:00",
        allDaySlot: false,
        height: "auto",
        nowIndicator: true,
        droppable: true,
        editable: true,
        events: eventsUrl,
        // A chip dropped from the sources list: create a real TimeBlock for
        // that task server-side, then drop the temporary FC-added event and
        // refetch so the block comes back styled/identified like any other.
        eventReceive: function (info) {
          var taskId = info.event.extendedProps.taskId;
          var start = info.event.start;
          var end = info.event.end || new Date(start.getTime() + 3600000);
          var url = createTpl.replace("/0/", "/" + taskId + "/");
          htmx.ajax("POST", url, {
            values: { start: start.toISOString(), end: end.toISOString() },
            swap: "none",
          }).then(function () {
            info.event.remove();
            calendar.refetchEvents();
          });
        },
        eventDrop: function (info) { patchBlock(info.event); },
        eventResize: function (info) { patchBlock(info.event); },
      });

      function patchBlock(event) {
        if (String(event.id).indexOf("block-") !== 0) return; // only our blocks
        var blockId = event.id.replace("block-", "");
        var url = updateTpl.replace("/0/", "/" + blockId + "/");
        htmx.ajax("POST", url, {
          values: { start: event.start.toISOString(), end: event.end.toISOString() },
          swap: "none",
        });
      }

      calendar.render();
      // The panel was hidden (x-show) until this open, so FC measured a
      // zero-height container; nudge it once now that it's visible.
      setTimeout(function () { calendar.updateSize(); }, 50);
    }).catch(function (err) { console.error("[today-plan]", err); });
  };
})();
