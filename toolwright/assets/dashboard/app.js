/* Toolwright Dashboard — SSE consumer + data fetcher */
(function () {
  "use strict";

  var token = null;
  var BASE = "";

  // --- Auth ---
  function initAuth() {
    var params = new URLSearchParams(window.location.search);
    var t = params.get("t");
    if (t) {
      token = t;
      // Strip token from URL bar
      var clean = window.location.pathname;
      window.history.replaceState({}, document.title, clean);
    }
  }

  function authHeaders() {
    var h = { Accept: "application/json" };
    if (token) h["Authorization"] = "Bearer " + token;
    return h;
  }

  // --- Fetch helpers ---
  function fetchJSON(path) {
    return fetch(BASE + path, { headers: authHeaders() }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  // --- DOM helpers ---
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "className") {
          node.className = attrs[k];
        } else {
          node.setAttribute(k, attrs[k]);
        }
      });
    }
    if (typeof children === "string") {
      node.textContent = children;
    } else if (Array.isArray(children)) {
      children.forEach(function (c) {
        if (c) node.appendChild(c);
      });
    }
    return node;
  }

  // --- Overview ---
  function loadOverview() {
    fetchJSON("/api/overview")
      .then(function (data) {
        setText("tool-count", String(data.tools || 0));
        setText("uptime", formatUptime(data.uptime || 0));
        var dot = document.getElementById("status");
        if (dot) dot.className = "status-dot";
      })
      .catch(function () {
        var dot = document.getElementById("status");
        if (dot) dot.style.background = "#EF4444";
      });
  }

  function setText(id, text) {
    var node = document.getElementById(id);
    if (node) node.textContent = text;
  }

  function formatUptime(seconds) {
    if (seconds < 60) return Math.floor(seconds) + "s";
    if (seconds < 3600) return Math.floor(seconds / 60) + "m";
    return Math.floor(seconds / 3600) + "h";
  }

  // --- Tools ---
  function loadTools() {
    fetchJSON("/api/tools")
      .then(function (tools) {
        var tbody = document.getElementById("tools-body");
        if (!tbody) return;
        // Clear existing rows
        while (tbody.firstChild) tbody.removeChild(tbody.firstChild);

        var healthy = 0;
        tools.forEach(function (tool) {
          var risk = tool.risk_tier || "low";
          var riskSpan = el("span", { className: "risk-" + risk }, risk);
          var row = el("tr", null, [
            el("td", null, tool.name || ""),
            el("td", null, (tool.method || "GET").toUpperCase()),
            el("td", null, tool.path || "/"),
            el("td", null, [riskSpan]),
          ]);
          tbody.appendChild(row);
          healthy++;
        });

        var total = tools.length || 1;
        var pct = Math.round((healthy / total) * 100);
        setText("health-pct", pct + "%");
      })
      .catch(function () {
        setText("health-pct", "?");
      });
  }

  // --- Events ---
  function addEvent(evt) {
    var feed = document.getElementById("events-feed");
    if (!feed) return;

    var ts = evt.timestamp
      ? new Date(evt.timestamp * 1000).toLocaleTimeString()
      : "";
    var line = el("div", { className: "event-line" }, [
      el("span", { className: "event-time" }, ts),
      el("span", { className: "event-type" }, evt.event_type || "unknown"),
      el("span", null, JSON.stringify(evt.data || {})),
    ]);

    // Prepend newest on top
    if (feed.firstChild) {
      feed.insertBefore(line, feed.firstChild);
    } else {
      feed.appendChild(line);
    }

    // Cap at 200 visible events
    while (feed.childNodes.length > 200) {
      feed.removeChild(feed.lastChild);
    }
  }

  function loadEvents() {
    fetchJSON("/api/events")
      .then(function (events) {
        events.forEach(addEvent);
      })
      .catch(function () {
        /* ignore */
      });
  }

  // --- SSE ---
  var retryDelay = 1000;
  var maxDelay = 30000;

  function connectSSE() {
    var url = BASE + "/api/events/stream";
    if (token) url += "?t=" + encodeURIComponent(token);

    var source = new EventSource(url);

    source.onopen = function () {
      retryDelay = 1000;
    };

    source.onmessage = function (msg) {
      try {
        var evt = JSON.parse(msg.data);
        addEvent(evt);
      } catch (_) {
        /* malformed event */
      }
    };

    source.onerror = function () {
      source.close();
      setTimeout(connectSSE, retryDelay);
      retryDelay = Math.min(retryDelay * 2, maxDelay);
    };
  }

  // --- Init ---
  function init() {
    initAuth();
    loadOverview();
    loadTools();
    loadEvents();
    connectSSE();
    // Refresh overview every 30s
    setInterval(loadOverview, 30000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
