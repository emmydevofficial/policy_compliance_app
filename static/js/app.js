// Alpine components. Registered here (not inline) so the CSP build needs no unsafe-eval.
(function () {
  function applyTheme(theme) {
    if (theme === "light" || theme === "dark") {
      document.documentElement.setAttribute("data-theme", theme);
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }
  var stored = null;
  try { stored = localStorage.getItem("od-theme"); } catch (e) { stored = null; }
  applyTheme(stored);

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("themeToggle", function () {
      return {
        label: "Theme: " + (stored || "system"),
        cycle: function () {
          var order = ["system", "light", "dark"];
          var current = document.documentElement.getAttribute("data-theme") || "system";
          var next = order[(order.indexOf(current) + 1) % order.length];
          applyTheme(next);
          try { localStorage.setItem("od-theme", next); } catch (e) { /* storage blocked */ }
          this.label = "Theme: " + next;
        },
      };
    });

    window.Alpine.data("menu", function () {
      return {
        open: false,
        toggle: function () { this.open = !this.open; },
      };
    });

    // Submission form: show the action-plan block only when the position needs one.
    window.Alpine.data("submissionForm", function () {
      return {
        status: "",
        evidence: "",
        init: function () {
          var s = this.$el.querySelector("[name=compliance_status]");
          var e = this.$el.querySelector("[name=evidence_available]");
          this.status = s ? s.value : "";
          this.evidence = e ? e.value : "";
        },
        setStatus: function (ev) { this.status = ev.target.value; },
        setEvidence: function (ev) { this.evidence = ev.target.value; },
        get needsPlan() { return this.status === "PARTIALLY_COMPLIANT" || this.status === "NON_COMPLIANT"; },
        get needsRemarks() { return this.status === "NOT_APPLICABLE"; },
        get noEvidence() { return this.evidence === "NO"; },
      };
    });

    // A plain disclosure: used for inline action panels.
    window.Alpine.data("disclosure", function () {
      return {
        open: false,
        toggle: function () { this.open = !this.open; },
      };
    });
  });

  // Confirmation for dangerous forms, without inline handlers.
  document.addEventListener("submit", function (ev) {
    var msg = ev.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) { ev.preventDefault(); }
  });
})();
