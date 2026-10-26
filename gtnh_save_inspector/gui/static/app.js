/* gtnh-save-inspector GUI — vanilla JS, no external dependencies. */
(() => {
  "use strict";

  const TOKEN = new URLSearchParams(location.search).get("token") || "";
  const $ = (id) => document.getElementById(id);
  const state = {
    config: {},
    worlds: [],
    world: null,
    entries: [],
    jobId: null,
    jobTimer: null,
    snapshots: [],
    diff: null,
    live: null,
    liveTimer: null,
    lang: "zh",
    theme: "light",
    selectedEntry: null,
    worldsDir: "",
    scanStatusKey: "",
    scanStatusExtra: "",
    scanStatusUnit: "",
    machineCandidates: [],
    version: "",
    sortKey: null,
    sortDir: null,
  };

  const BUILTIN_MACHINE_CLASSES = [
    "MTEEyeOfHarmony",
    "PurificationUnit",
    "QuantumComputer",
    "DataBank",
    "ResearchStation",
    "GTMultiblock",
    "GTMachine",
  ];

  // ---------------------------------------------------------------- helpers
  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setScanStatus(key, extra = "", unit = "") {
    state.scanStatusKey = key;
    state.scanStatusExtra = extra;
    state.scanStatusUnit = unit;
    $("browse-status").textContent = key
      ? t(key) + (extra ? " " + extra : "") + (unit ? " " + t(unit) : "")
      : "";
  }

  function updateWorldsMessage() {
    if (state.worldsDir === null || state.worldsDir === undefined) return;
    const suffix = state.worldsDir ? " · " + state.worldsDir : "";
    $("worlds-message").textContent = state.worlds.length + " " + t("worlds.count") + suffix;
  }

  function toast(message, isError = false) {
    const box = $("toast");
    box.textContent = message;
    box.className = "toast" + (isError ? " err" : "");
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => box.classList.add("hidden"), 4500);
  }

  async function api(path, options = {}) {
    const headers = Object.assign({ "X-GTNH-Token": TOKEN }, options.headers || {});
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    const response = await fetch(path, Object.assign({}, options, { headers }));
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    if (!response.ok) {
      const message = payload && payload.error ? payload.error : "HTTP " + response.status;
      throw new Error(message);
    }
    return payload;
  }

  function triggerDownload(url, name) {
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function download(name) {
    triggerDownload(
      "/api/download?name=" + encodeURIComponent(name) + "&token=" + encodeURIComponent(TOKEN),
      name
    );
  }

  function downloadPath(path, name) {
    triggerDownload(
      "/api/download?path=" + encodeURIComponent(path) + "&token=" + encodeURIComponent(TOKEN),
      name
    );
  }

  function asLines(value) {
    return String(value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function rememberMachineClasses(entries) {
    for (const entry of entries || []) {
      const name = entry && entry.machine;
      if (name && name !== "GTMachine") state.machineCandidates.push(name);
    }
  }

  function refreshMachineCandidates() {
    const classes = new Set(BUILTIN_MACHINE_CLASSES);
    for (const name of state.machineCandidates) classes.add(name);
    for (const entry of state.entries) if (entry.machine) classes.add(entry.machine);
    if (state.live && state.live.entries) {
      for (const entry of state.live.entries) if (entry.machine) classes.add(entry.machine);
    }
    for (const id of ["live-machine", "browse-mte"]) {
      const element = $(id);
      if (!element) continue;
      for (const name of element.value.split(",")) {
        if (name.trim()) classes.add(name.trim());
      }
    }
    const options = [...classes].sort((a, b) => a.localeCompare(b));
    const markup = options
      .map((name) => '<option value="' + esc(name) + '"></option>')
      .join("");
    for (const id of ["live-machine-options", "browse-machine-options"]) {
      const element = $(id);
      if (element) element.innerHTML = markup;
    }
  }

  function field(entry, name) {
    return (entry && entry.fields ? entry.fields[name] : undefined);
  }

  function progressText(entry) {
    const current = field(entry, "progress");
    const maximum = field(entry, "max");
    if (current === undefined || current === null) return "";
    return maximum ? current + "/" + maximum : String(current);
  }

  // ---------------------------------------------------------------- i18n / theme
  function applyLang() {
    window.GTNH_LANG = state.lang;
    document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
    document.querySelectorAll("[data-i18n]").forEach((node) => {
      const key = node.dataset.i18n;
      const text = t(key);
      if (text && text !== key) node.textContent = text;
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
      node.placeholder = t(node.dataset.i18nPlaceholder);
    });
    $("lang-toggle").textContent = state.lang === "zh" ? "EN" : "中";
    applyTheme();
    if (state.worlds.length) renderWorlds();
    if (state.entries.length) renderEntries();
    if (state.diff) renderDiff();
    if (state.live) renderLive();
    updateWorldsMessage();
    if (state.scanStatusKey) {
      setScanStatus(state.scanStatusKey, state.scanStatusExtra, state.scanStatusUnit);
    }
    if (!state.snapshots.length) $("snap-status").textContent = t("snap.none");
    if (document.getElementById("panel-settings").classList.contains("active")) {
      loadSettings();
    }
  }

  function applyTheme() {
    document.body.dataset.theme = state.theme;
    const toggle = $("theme-toggle");
    toggle.textContent = state.theme === "dark" ? "◑" : "◐";
    toggle.title = t("app.theme");
  }

  // ---------------------------------------------------------------- tabs
  function showTab(name) {
    document.querySelectorAll(".tab").forEach((tab) => {
      const active = tab.dataset.tab === name;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll(".panel").forEach((panel) => {
      panel.classList.toggle("active", panel.id === "panel-" + name);
    });
    if (name === "snapshots") refreshSnapshots();
    if (name === "settings") loadSettings();
  }

  // ---------------------------------------------------------------- worlds
  async function loadWorlds(directory) {
    const dirInput = $("worlds-dir");
    const dir = directory !== undefined ? directory : dirInput.value.trim();
    $("worlds-message").textContent = t("app.loading");
    try {
      const data = await api("/api/worlds?dir=" + encodeURIComponent(dir));
      state.worlds = data.worlds || [];
      state.worldsDir = data.dir || dir;
      dirInput.value = state.worldsDir;
      if (state.world && !state.worlds.some((world) => world.path === state.world.path)) {
        state.world = null;
      }
      renderWorlds();
      fillWorldSelects();
      updateWorldsMessage();
      if (!state.world && state.worlds.length) {
        const preferred = state.worlds.find((world) => world.path === state.config.world);
        selectWorld(preferred || state.worlds[0]);
      }
    } catch (error) {
      state.worldsDir = null;
      $("worlds-message").textContent = error.message + " — " + t("worlds.hint");
      toast(error.message, true);
    }
  }

  function renderWorlds() {
    const list = $("worlds-list");
    if (!state.worlds.length) {
      list.innerHTML = '<div class="card muted">' + esc(t("worlds.empty")) + "</div>";
      return;
    }
    list.innerHTML = state.worlds
      .map((world, index) => {
        const selected = state.world && state.world.path === world.path ? " selected" : "";
        const kind = world.kind === "zip-backup" ? " · " + t("worlds.backup") : "";
        return (
          '<div class="card world-card' + selected + '" role="button" tabindex="0" data-index="' + index + '">' +
          '<div class="name">' + esc(world.name) + "</div>" +
          '<div class="meta">' + esc(world.kind) + kind + " · " + world.dims.length + " dims</div>" +
          '<div class="meta">' + esc(world.path) + "</div>" +
          "</div>"
        );
      })
      .join("");
    const choose = (card) => selectWorld(state.worlds[Number(card.dataset.index)]);
    list.querySelectorAll(".world-card").forEach((card) => {
      card.addEventListener("click", () => choose(card));
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          choose(card);
        }
      });
    });
  }

  function selectWorld(world) {
    const changed = state.world && world && state.world.path !== world.path;
    const firstSelection = !state.world && world;
    state.world = world;
    if (world && (changed || firstSelection)) {
      saveConfigQuiet("world", world.path);
    }
    if (changed) {
      state.entries = [];
      state.jobId = null;
      state.selectedEntry = null;
      state.scanWorld = null;
      renderEntries();
      $("detail-pos").textContent = "";
      $("detail-body").innerHTML = '<span class="muted">' + esc(t("browse.selectHint")) + "</span>";
      $("detail-raw-box").classList.add("hidden");
    }
    renderWorlds();
    fillWorldSelects();
    if (world) {
      $("browse-dims-hint").textContent = world.dims.join(", ");
      updateWorldsMessage();
    }
  }

  function fillWorldSelects() {
    const options = state.worlds
      .map((world) => '<option value="' + esc(world.path) + '">' + esc(world.name) + "</option>")
      .join("");
    for (const id of ["browse-world", "live-world"]) {
      const select = $(id);
      if (!select) continue;
      select.innerHTML = '<option value="">' + esc(t("app.noWorld")) + "</option>" + options;
      if (state.world) select.value = state.world.path;
    }
  }

  // ---------------------------------------------------------------- browse
  async function startScan() {
    if (!state.world) {
      toast(t("app.noWorld"), true);
      return;
    }
    if (state.jobId) {
      try {
        await api("/api/jobs/" + state.jobId + "/cancel", { method: "POST", body: "{}" });
      } catch (ignored) {
        /* the previous job may already be finished */
      }
      clearTimeout(state.jobTimer);
      state.jobId = null;
    }
    state.scanWorld = $("browse-world").value || state.world.path;
    setScanStatus("browse.scanning");
    $("browse-progress").style.width = "0%";
    $("browse-table").querySelector("tbody").innerHTML = "";
    $("browse-count").textContent = "";
    try {
      const job = await api("/api/jobs/scan", {
        method: "POST",
        body: JSON.stringify({
          world: $("browse-world").value || state.world.path,
          dims: asLines($("browse-dims").value),
          mte: $("browse-mte").value || null,
          where: $("browse-where").value.trim() || null,
          jobs: Number($("browse-jobs").value || 1),
          all: $("browse-all").checked,
          fast: $("browse-fast").checked,
        }),
      });
      state.jobId = job.id;
      pollScanJob();
    } catch (error) {
      setScanStatus("browse.scanFailed", ": " + error.message);
      toast(error.message, true);
    }
  }

  async function pollScanJob() {
    clearTimeout(state.jobTimer);
    if (!state.jobId) return;
    try {
      const job = await api("/api/jobs/" + state.jobId);
      const percent = Math.round((job.progress || 0) * 100);
      $("browse-progress").style.width = percent + "%";
      if (job.status === "running") {
        setScanStatus("browse.scanning", percent + "%");
        state.jobTimer = setTimeout(pollScanJob, 400);
        return;
      }
      if (job.status === "error") {
        state.jobId = null;
        setScanStatus("browse.scanFailed", ": " + (job.error || ""));
        toast(job.error || t("browse.scanFailed"), true);
        return;
      }
      if (job.status === "cancelled") {
        state.jobId = null;
        setScanStatus("");
        toast(t("live.cancelled"));
        return;
      }
      state.entries = (job.result && job.result.entries) || [];
      rememberMachineClasses(state.entries);
      refreshMachineCandidates();
      renderEntries();
      setScanStatus("browse.done", "· " + state.entries.length, "browse.entries");
    } catch (error) {
      toast(error.message, true);
    }
  }

  function sortValue(entry, key) {
    const value = field(entry, key);
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function displayedEntries() {
    const rows = state.entries.slice();
    if (!state.sortKey || !state.sortDir) return rows;
    const factor = state.sortDir === "asc" ? 1 : -1;
    rows.sort((left, right) => {
      const a = sortValue(left, state.sortKey);
      const b = sortValue(right, state.sortKey);
      if (a === null && b === null) return 0;
      if (a === null) return 1;
      if (b === null) return -1;
      if (a === b) return 0;
      return a < b ? -factor : factor;
    });
    return rows;
  }

  function toggleSort(key) {
    if (state.sortKey !== key) {
      state.sortKey = key;
      state.sortDir = "asc";
    } else if (state.sortDir === "asc") {
      state.sortDir = "desc";
    } else {
      state.sortKey = null;
      state.sortDir = null;
    }
    renderEntries();
  }

  function renderEntries() {
    const table = $("browse-table");
    const sortable = new Set(["progress", "totalRun"]);
    const columns = ["dim", "pos", "machine", "progress", "totalRun", "shutdown", "checkRecipe"];
    table.querySelector("thead").innerHTML =
      "<tr>" + columns.map((name) => {
        if (!sortable.has(name)) return "<th>" + esc(name) + "</th>";
        const active = state.sortKey === name;
        const direction = active ? state.sortDir : null;
        const arrow = direction === "asc" ? "↓" : direction === "desc" ? "↑" : "↕";
        const aria = direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none";
        return '<th data-sort="' + name + '" class="sortable" role="button" tabindex="0" aria-sort="' +
          aria + '">' + esc(name) + '<span class="sort-indicator">' + arrow + "</span></th>";
      }).join("") + "</tr>";
    const rows = displayedEntries().slice(0, 500);
    table.querySelector("tbody").innerHTML = rows
      .map((entry, index) => {
        const cells = [
          entry.dim,
          "(" + (entry.pos || []).join(",") + ")",
          entry.machine,
          progressText(entry),
          field(entry, "totalRun"),
          field(entry, "shutdown"),
          field(entry, "checkRecipe"),
        ];
        return (
          '<tr data-index="' + index + '" tabindex="0">' +
          cells.map((cell) => "<td>" + esc(cell) + "</td>").join("") +
          "</tr>"
        );
      })
      .join("");
    $("browse-count").textContent =
      state.entries.length +
      " " + t("browse.entries") +
      (state.entries.length > rows.length
        ? " · " + t("browse.showing") + " " + rows.length
        : "");
    table.querySelectorAll("th[data-sort]").forEach((header) => {
      const activate = () => toggleSort(header.dataset.sort);
      header.addEventListener("click", activate);
      header.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      });
    });
    table.querySelectorAll("tbody tr").forEach((row) => {
      const choose = () => {
        table.querySelectorAll("tbody tr").forEach((item) => item.classList.remove("selected"));
        row.classList.add("selected");
        showEntryDetail(rows[Number(row.dataset.index)]);
      };
      row.addEventListener("click", choose);
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          choose();
        }
      });
    });
  }

  async function showEntryDetail(entry) {
    state.selectedEntry = entry;
    $("detail-pos").textContent =
      entry.dim + " (" + (entry.pos || []).join(",") + ") " + (entry.machine || "");
    const fields = entry.fields || {};
    const keys = Object.keys(fields).sort();
    const rows = keys
      .filter((key) => fields[key] !== undefined)
      .map(
        (key) =>
          '<div class="k">' + esc(key) + '</div><div class="v">' +
          esc(JSON.stringify(fields[key])) + "</div>"
      )
      .join("");
    $("detail-body").innerHTML = '<div class="kv">' + rows + "</div>";
    $("detail-raw-box").classList.add("hidden");
  }

  async function showRawNbt() {
    const entry = state.selectedEntry;
    if (!entry) return;
    try {
      const worldPath = state.scanWorld || (state.world ? state.world.path : "");
      const detail = await api(
        "/api/entry?world=" + encodeURIComponent(worldPath) +
        "&dim=" + encodeURIComponent(entry.dim) +
        "&pos=" + encodeURIComponent((entry.pos || []).join(","))
      );
      const box = $("detail-raw-box");
      box.textContent = JSON.stringify(detail.raw, null, 2);
      box.classList.toggle("hidden");
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function exportCurrent(format) {
    if (!state.jobId) {
      toast(t("browse.scan"), true);
      return;
    }
    try {
      const result = await api("/api/export", {
        method: "POST",
        body: JSON.stringify({ job_id: state.jobId, format }),
      });
      if (format === "snapshot") {
        await refreshSnapshots();
        toast(t("browse.saved") + (result.path ? ": " + result.path : ""));
      } else {
        toast(t("browse.exported") + ": " + (result.path || result.file));
        if (result.path) {
          downloadPath(result.path, result.file);
        } else {
          download(result.file);
        }
      }
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ---------------------------------------------------------------- snapshots
  async function refreshSnapshots() {
    try {
      const data = await api("/api/snapshots");
      state.snapshots = data.snapshots || [];
      const options = state.snapshots
        .map(
          (snapshot) =>
            '<option value="' + esc(snapshot.path) + '">' +
            esc(snapshot.path.split(/[\\/]/).pop()) +
            " · " + snapshot.entries + " " + t("browse.entries") + "</option>"
        )
        .join("");
      for (const id of ["snap-a", "snap-b"]) {
        const select = $(id);
        const previous = select.value;
        select.innerHTML = options;
        if (previous) select.value = previous;
      }
      const paths = state.snapshots.map((snapshot) => snapshot.path);
      const valid = new Set(paths);
      let a = $("snap-a").value;
      let b = $("snap-b").value;
      if (!valid.has(a) || !valid.has(b) || a === b) {
        const ordered = [...state.snapshots].sort((left, right) =>
          String(left.captured || "").localeCompare(String(right.captured || ""))
        );
        $("snap-a").value = ordered.length ? ordered[0].path : "";
        $("snap-b").value = ordered.length ? ordered[ordered.length - 1].path : "";
      }
      if (!state.snapshots.length) {
        $("snap-status").textContent = t("snap.none");
      } else if ($("snap-status").textContent === t("snap.none")) {
        $("snap-status").textContent = "";
      }
    } catch (error) {
      toast(error.message, true);
    }
  }

  function downloadSnapshot(which) {
    const select = $(which === "a" ? "snap-a" : "snap-b");
    const path = select.value;
    if (!path) {
      toast(t("snap.none"), true);
      return;
    }
    const url = "/api/download?path=" + encodeURIComponent(path) +
      "&token=" + encodeURIComponent(TOKEN);
    const link = document.createElement("a");
    link.href = url;
    link.download = path.split(/[\\/]/).pop();
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function importSnapshot() {
    const path = $("snap-import-path").value.trim();
    if (!path) return;
    try {
      await api("/api/snapshots/import", {
        method: "POST",
        body: JSON.stringify({ path }),
      });
      $("snap-import-path").value = "";
      await refreshSnapshots();
      toast(t("snap.imported"));
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function runDiff() {
    const a = $("snap-a").value;
    const b = $("snap-b").value;
    if (!a || !b) {
      toast(t("snap.none"), true);
      return;
    }
    $("snap-status").textContent = t("app.loading");
    try {
      const result = await api("/api/diff", {
        method: "POST",
        body: JSON.stringify({
          a,
          b,
          ignore: asLines($("snap-ignore").value),
          machine: $("snap-machine").value.trim() || null,
        }),
      });
      state.diff = result;
      renderDiff();
    } catch (error) {
      $("snap-status").textContent = error.message;
      toast(error.message, true);
    }
  }

  function renderDiff() {
    const result = state.diff;
    const changes = result.changes || [];
    const added = changes.filter((change) => change.status === "added").length;
    const removed = changes.filter((change) => change.status === "removed").length;
    const changed = changes.filter((change) => change.status === "changed").length;
    $("snap-summary").textContent =
      changes.length + " " + t("snap.summary") + " · " +
      added + " " + t("snap.added") + " · " +
      removed + " " + t("snap.removed") + " · " +
      changed + " " + t("snap.changed");
    const metaDiff = result.meta_diff || {};
    const metaKeys = Object.keys(metaDiff);
    const meta = $("snap-meta");
    if (metaKeys.length) {
      meta.classList.remove("hidden");
      meta.textContent = t("snap.metaWarn") + ": " + metaKeys
        .map((key) => key + " " + JSON.stringify(metaDiff[key].a) + " → " +
             JSON.stringify(metaDiff[key].b))
        .join("; ");
    } else {
      meta.classList.add("hidden");
    }
    const table = $("snap-table");
    table.querySelector("thead").innerHTML =
      "<tr><th>status</th><th>dim</th><th>pos</th><th>machine</th><th>fields</th></tr>";
    table.querySelector("tbody").innerHTML = changes
      .slice(0, 500)
      .map((change) => {
        let fields = change.fields
          ? Object.entries(change.fields)
              .map(([name, values]) => name + ": " + values.before + " → " + values.after)
              .join("; ")
          : "";
        if (change.machine_before && change.machine_before !== change.machine_after) {
          fields = "machine: " + change.machine_before + " → " + change.machine_after +
            (fields ? "; " + fields : "");
        }
        return (
          "<tr><td><span class=\"badge " + esc(change.status) + "\">" + esc(change.status) + "</span></td>" +
          "<td>" + esc(change.dim) + "</td>" +
          "<td>(" + esc((change.pos || []).join(",")) + ")</td>" +
          "<td>" + esc(change.machine) + "</td>" +
          "<td>" + esc(fields) + "</td></tr>"
        );
      })
      .join("");
    if (!changes.length) {
      $("snap-status").textContent = asLines($("snap-ignore").value).length
        ? t("snap.noDiffIgnore")
        : t("snap.noDiff");
    } else {
      $("snap-status").textContent = "";
    }
  }

  // ---------------------------------------------------------------- live
  async function findGames() {
    try {
      const data = await api("/api/probe/find");
      const games = data.games || [];
      if (!games.length) {
        $("live-games").textContent = t("live.noGame");
        return;
      }
      $("live-games").textContent = games
        .map((game) => "pid " + game.pid + " · " + (game.instance || "GTNH"))
        .join(" | ");
      $("live-pid").value = String(games[0].pid);
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function connectLive() {
    const pidValue = $("live-pid").value.trim();
    if (pidValue && pidValue !== "auto" && !/^\d+$/.test(pidValue)) {
      toast(t("live.pid") + ": " + pidValue, true);
      return;
    }
    refreshMachineCandidates();
    try {
      const data = await api("/api/probe/connect", {
        method: "POST",
        body: JSON.stringify({
          pid: pidValue || "auto",
          world: $("live-world").value || (state.world ? state.world.path : null),
          machine: $("live-machine").value.trim() || null,
          dims: asLines($("live-dims").value),
          max: Number($("live-max").value || 200),
          interval: Number($("live-interval").value || 1000),
          all: $("live-all").checked,
          changes: $("live-changes").checked,
          min_delta: Number($("live-min-delta").value || 0),
          until: asLines($("live-until").value),
        }),
      });
      state.live = data;
      pollLive();
    } catch (error) {
      toast(error.message, true);
      await pollLive();
    }
  }

  async function pollLive() {
    clearTimeout(state.liveTimer);
    const previous = state.live;
    try {
      const data = await api("/api/probe/state");
      state.live = data;
      renderLive();
      if (["running", "connecting", "no-server"].includes(data.status)) {
        state.liveTimer = setTimeout(pollLive, 1000);
      } else if (previous && ["running", "connecting", "no-server"].includes(previous.status)) {
        // Do not let a transient "disconnected" during inspect/attach freeze the UI.
        state.liveTimer = setTimeout(pollLive, 1500);
      }
    } catch (error) {
      toast(error.message, true);
    }
  }

  function renderLive() {
    const data = state.live || { status: "disconnected" };
    const key = "live.status." + data.status;
    const translated = t(key);
    const label = translated === key ? data.status : translated;
    $("live-status").textContent =
      label + (data.tick !== undefined && data.tick !== null ? " · tick " + data.tick : "") +
      (data.pid ? " · pid " + data.pid : "") +
      (data.error ? " · " + data.error : "");
    const active = ["running", "connecting", "no-server"].includes(data.status);
    $("live-changes").disabled = active;
    const alert = $("live-alert");
    if (data.alert) {
      alert.classList.remove("hidden");
      alert.textContent = t("live.alert") + " · tick " + data.alert.tick +
        " · " + data.alert.count + " " + t("browse.entries");
    } else {
      alert.classList.add("hidden");
    }
    const changes = data.changes || [];
    const entries = data.entries || [];
    rememberMachineClasses(entries);
    const table = $("live-table");
    const useChanges = data.changes_enabled !== undefined
      ? data.changes_enabled
      : $("live-changes").checked;
    const columns = useChanges
      ? ["status", "dim", "pos", "machine"]
      : ["dim", "pos", "machine", "progress", "totalRun", "shutdown"];
    table.querySelector("thead").innerHTML =
      "<tr>" + columns.map((name) => "<th>" + esc(name) + "</th>").join("") + "</tr>";
    const rows = useChanges ? changes.slice(0, 500) : entries.slice(0, 500);
    table.querySelector("tbody").innerHTML = rows
      .map((item) => {
        const cells = useChanges
          ? [item.status, item.dim, "(" + (item.pos || []).join(",") + ")", item.machine]
          : [item.dim, "(" + (item.pos || []).join(",") + ")", item.machine,
             progressText(item), field(item, "totalRun"), field(item, "shutdown")];
        return "<tr>" + cells.map((cell) => "<td>" + esc(cell) + "</td>").join("") + "</tr>";
      })
      .join("");
    $("live-count").textContent =
      useChanges
        ? rows.length + " " + t("live.changesCount")
        : entries.length + " " + t("browse.entries") +
          (data.samples ? " · " + data.samples + " " + t("live.samples") : "");
  }

  async function stopLive() {
    try {
      state.live = await api("/api/probe/stop", { method: "POST", body: "{}" });
      clearTimeout(state.liveTimer);
      renderLive();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function saveLive() {
    try {
      await api("/api/probe/save", { method: "POST", body: "{}" });
      await refreshSnapshots();
      toast(t("live.saved"));
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function inspectChunk() {
    if (!$("inspect-dim").value || !$("inspect-x").value || !$("inspect-z").value) {
      toast(t("app.noData"), true);
      return;
    }
    try {
      const result = await api("/api/probe/chunk", {
        method: "POST",
        body: JSON.stringify({
          pid: $("live-pid").value.trim() || "auto",
          dim: Number($("inspect-dim").value),
          x: Number($("inspect-x").value),
          z: Number($("inspect-z").value),
        }),
      });
      $("inspect-result").textContent = JSON.stringify(result, null, 2);
      if (result.watch_resumed) {
        toast(t("live.watchResumed"));
      } else if (result.watch_stopped) {
        toast(t("live.watchStopped"), true);
      }
      await pollLive();
    } catch (error) {
      $("inspect-result").textContent = t("app.error") + ": " + error.message;
      toast(error.message, true);
    }
  }

  async function inspectTe() {
    if (!$("inspect-dim").value || !$("inspect-pos").value.trim()) {
      toast(t("app.noData"), true);
      return;
    }
    try {
      const result = await api("/api/probe/te", {
        method: "POST",
        body: JSON.stringify({
          pid: $("live-pid").value.trim() || "auto",
          dim: Number($("inspect-dim").value),
          pos: $("inspect-pos").value.trim(),
        }),
      });
      $("inspect-result").textContent = JSON.stringify(result, null, 2);
      if (result.watch_resumed) {
        toast(t("live.watchResumed"));
      } else if (result.watch_stopped) {
        toast(t("live.watchStopped"), true);
      }
      await pollLive();
    } catch (error) {
      $("inspect-result").textContent = t("app.error") + ": " + error.message;
      toast(error.message, true);
    }
  }

  // ---------------------------------------------------------------- settings
  async function cleanWorkspace() {
    if (!window.confirm(t("cfg.cleanConfirm"))) return;
    try {
      const result = await api("/api/workspace/clean", {
        method: "POST",
        body: JSON.stringify({ keep: 0 }),
      });
      $("settings-status").textContent = t("cfg.cleaned") + ": " + result.removed;
      await refreshSnapshots();
    } catch (error) {
      toast(error.message, true);
    }
  }

  function saveConfigQuiet(key, value) {
    const body = {};
    body[key] = value;
    api("/api/config", { method: "POST", body: JSON.stringify(body) })
      .then((data) => {
        state.config = data.config || state.config;
      })
      .catch(() => {
        /* normal UI must not fail because a best-effort preference write failed */
      });
  }

  async function loadSettings() {
    try {
      const data = await api("/api/config");
      state.config = data.config || {};
      $("cfg-world").value = state.config.world || "";
      $("cfg-saves").value = state.config.saves || "";
      $("cfg-snapshot-dir").value = state.config.snapshot_dir || "";
      $("cfg-csv-dir").value = state.config.csv_dir || "";
      $("cfg-pid").value = state.config.pid !== undefined ? state.config.pid : "";
      $("cfg-java").value = state.config.java || "";
      $("about").innerHTML =
        "<strong>" + esc(t("settings.about")) + "</strong><br>" +
        "gtnh-save-inspector <span class='muted'>v" + esc(state.version) + "</span><br>" +
        "<span class='muted'>" + esc(data.path) + "</span>";
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function savePreference(key, value) {
    try {
      const body = {};
      body[key] = value;
      const data = await api("/api/config", { method: "POST", body: JSON.stringify(body) });
      state.config = data.config || state.config;
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function saveSettings() {
    const pidText = $("cfg-pid").value.trim();
    if (pidText && !/^\d+$/.test(pidText)) {
      toast(t("settings.pid") + ": " + pidText, true);
      return;
    }
    try {
      const body = {
        world: $("cfg-world").value.trim(),
        saves: $("cfg-saves").value.trim(),
        snapshot_dir: $("cfg-snapshot-dir").value.trim(),
        csv_dir: $("cfg-csv-dir").value.trim(),
        pid: pidText ? Number(pidText) : null,
        java: $("cfg-java").value.trim(),
      };
      const data = await api("/api/config", { method: "POST", body: JSON.stringify(body) });
      state.config = data.config || {};
      toast(t("settings.saved"));
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ---------------------------------------------------------------- boot
  async function boot() {
    if (!TOKEN) {
      toast(t("app.missingToken"), true);
      return;
    }
    try {
      const version = await api("/api/version");
      state.version = version.version;
    } catch (error) {
      toast(error.message, true);
      return;
    }
    try {
      const config = await api("/api/config");
      state.config = config.config || {};
      state.lang = state.config.language || "zh";
      state.theme = state.config.theme || "light";
    } catch (error) {
      state.lang = "zh";
      state.theme = "light";
    }
    applyLang();
    applyTheme();
    const saves = state.config.saves || "";
    $("worlds-dir").value = saves;
    await loadWorlds(saves);
    await refreshSnapshots();
    await pollLive();
    $("browse-world").addEventListener("change", () => {
      const found = state.worlds.find((world) => world.path === $("browse-world").value);
      if (found) selectWorld(found);
    });
    $("live-world").addEventListener("change", () => {
      const found = state.worlds.find((world) => world.path === $("live-world").value);
      if (found) selectWorld(found);
    });
  }

  // ---------------------------------------------------------------- events
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => showTab(tab.dataset.tab));
  });
  $("worlds-load").addEventListener("click", () => loadWorlds());
  $("lang-toggle").addEventListener("click", () => {
    state.lang = state.lang === "zh" ? "en" : "zh";
    applyLang();
    savePreference("language", state.lang);
  });
  $("theme-toggle").addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    applyTheme();
    savePreference("theme", state.theme);
  });
  $("browse-scan").addEventListener("click", startScan);
  $("browse-cancel").addEventListener("click", async () => {
    if (!state.jobId) return;
    try {
      await api("/api/jobs/" + state.jobId + "/cancel", { method: "POST", body: "{}" });
      toast(t("live.cancelling"));
    } catch (error) {
      toast(error.message, true);
    }
  });
  $("detail-raw").addEventListener("click", showRawNbt);
  $("export-csv").addEventListener("click", () => exportCurrent("csv"));
  $("export-snapshot").addEventListener("click", () => exportCurrent("snapshot"));
  $("snap-refresh").addEventListener("click", refreshSnapshots);
  $("snap-import").addEventListener("click", importSnapshot);
  $("snap-download-a").addEventListener("click", () => downloadSnapshot("a"));
  $("snap-download-b").addEventListener("click", () => downloadSnapshot("b"));
  $("snap-diff").addEventListener("click", runDiff);
  $("live-find").addEventListener("click", findGames);
  $("live-connect").addEventListener("click", connectLive);
  $("live-machine").addEventListener("focus", refreshMachineCandidates);
  $("browse-mte").addEventListener("focus", refreshMachineCandidates);
  $("live-stop").addEventListener("click", stopLive);
  $("live-save").addEventListener("click", saveLive);
  $("inspect-chunk").addEventListener("click", inspectChunk);
  $("inspect-te").addEventListener("click", inspectTe);
  $("cfg-save").addEventListener("click", saveSettings);

  window.addEventListener("beforeunload", () => {
    if (state.live && ["running", "connecting", "no-server"].includes(state.live.status)) {
      navigator.sendBeacon("/api/probe/stop?token=" + encodeURIComponent(TOKEN));
    }
  });

  refreshMachineCandidates();
  boot();
})();
