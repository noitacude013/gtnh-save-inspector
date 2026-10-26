/**
 * Headless DOM smoke test for the gtnh-save-inspector GUI.
 * Run with: node tests/frontend_smoke.mjs  (requires `npm install`)
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const staticDir = path.join(root, "gtnh_save_inspector", "gui", "static");
const html = fs.readFileSync(path.join(staticDir, "index.html"), "utf-8");
const i18n = fs.readFileSync(path.join(staticDir, "i18n.js"), "utf-8");
const app = fs.readFileSync(path.join(staticDir, "app.js"), "utf-8");

const failures = [];
function check(name, condition, detail = "") {
  console.log(`${condition ? "PASS" : "FAIL"} ${name}${detail ? "  " + detail : ""}`);
  if (!condition) failures.push(name);
}
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function response(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
    text: async () => JSON.stringify(data),
    blob: async () => new Blob([JSON.stringify(data)]),
  };
}

const dom = new JSDOM(html, {
  url: "http://127.0.0.1:1/?token=test-token",
  runScripts: "outside-only",
  pretendToBeVisual: true,
});
const { window } = dom;
const errors = [];
window.addEventListener("error", (event) => errors.push(String(event.error || event.message)));
window.addEventListener("unhandledrejection", (event) => errors.push(String(event.reason)));

let probeStatus = "disconnected";
const connectCalls = [];

const doneJob = {
  id: "job-1",
  status: "done",
  progress: 1,
  message: "1 entries",
  result: {
    dims: ["overworld"],
    entries: [
      {
        dim: "overworld",
        pos: [10, 64, 10],
        machine: "DynamicProbeClass",
        chunk: [0, 0],
        fields: { progress: 12345, totalRun: 500 },
      },
      {
        dim: "overworld",
        pos: [1, 64, 1],
        machine: "MTEEyeOfHarmony",
        chunk: [0, 0],
        fields: { progress: 100, totalRun: 900 },
      },
    ],
  },
};

window.fetch = async (input, options) => {
  const raw = typeof input === "string" ? input : input.url;
  const url = new URL(raw, "http://127.0.0.1:1");
  const route = url.pathname;
  if (route === "/api/version") return response({ version: "test" });
  if (route === "/api/config") {
    return response({ config: { language: "zh", theme: "light" }, path: "/tmp/config.json" });
  }
  if (route === "/api/worlds") {
    return response({
      dir: "/saves",
      worlds: [
        {
          name: "Horizon",
          path: "/saves/Horizon",
          dims: ["overworld", "PERSONAL_DIM_180"],
          size: 1024,
          mtime: 1,
          backup: false,
        },
      ],
    });
  }
  if (route === "/api/snapshots") {
    return response({
      snapshots: [
        {
          path: "/tmp/a.json",
          captured: "2026-01-01T00:00:00",
          source: "a",
          world: "a",
          entries: 1,
          meta: {},
        },
      ],
    });
  }
  if (route === "/api/probe/state") {
    return response({
      status: probeStatus,
      samples: probeStatus === "running" ? 1 : 0,
      entries: [],
      changes: [],
      changes_enabled: false,
    });
  }
  if (route === "/api/probe/connect") {
    connectCalls.push(JSON.parse((options && options.body) || "{}"));
    probeStatus = "running";
    return response({ status: "running", samples: 1, entries: [], changes: [] });
  }
  if (route === "/api/probe/stop") {
    probeStatus = "disconnected";
    return response({ status: "stopped" });
  }
  if (route === "/api/probe/find") return response({ games: [{ pid: 1, title: "GTNH" }] });
  if (route === "/api/jobs/scan") return response({ id: "job-1" }, 202);
  if (route === "/api/jobs/job-1") return response(doneJob);
  if (route === "/api/export") return response({ file: "export.csv" });
  if (route === "/api/entry") {
    return response({
      dim: "overworld",
      pos: [10, 64, 10],
      machine: "MTEEyeOfHarmony",
      fields: { progress: 12345 },
    });
  }
  if (route === "/api/workspace/clean") return response({ removed: 0, kept: 0 });
  return response({}, 404);
};
try {
  Object.defineProperty(window.navigator, "sendBeacon", { value: () => true });
} catch (error) {
  /* jsdom may expose a read-only navigator */
}

window.eval(i18n);
window.eval(app);

await wait(900);
try {
  check("world cards rendered", window.document.querySelectorAll(".world-card").length === 1);
  check(
    "initial tab aria-selected",
    window.document.querySelector('[data-tab="worlds"]').getAttribute("aria-selected") === "true",
  );
  check(
    "header does not show version",
    !window.document.querySelector("#version") &&
      !window.document.querySelector(".title").textContent.includes("v1."),
  );
  window.document.querySelector('[data-tab="settings"]').click();
  await wait(400);
  check(
    "about shows version",
    window.document.getElementById("about").textContent.includes("vtest"),
  );
  window.document.querySelector('[data-tab="worlds"]').click();
  check(
    "labels associated",
    window.document.querySelectorAll("label[for]").length >= 20,
    String(window.document.querySelectorAll("label[for]").length),
  );

  const card = window.document.querySelector(".world-card");
  card.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  window.document.querySelector('[data-tab="browse"]').click();
  check(
    "browse machine datalist has built-ins",
    [...window.document.querySelectorAll("#browse-machine-options option")].some(
      (option) => option.value === "MTEEyeOfHarmony",
    ),
  );
  window.document.getElementById("browse-mte").value = "MTEEyeOfHarmony";
  window.document.getElementById("browse-dims").value = "180";
  window.document.getElementById("browse-scan").click();
  await wait(1400);

  let rows = window.document.querySelectorAll("#browse-table tbody tr");
  check("scan renders result rows", rows.length === 2, String(rows.length));
  check(
    "dynamic machine class merged into datalist",
    [...window.document.querySelectorAll("#live-machine-options option")].some(
      (option) => option.value === "DynamicProbeClass",
    ),
  );
  // progress header: asc -> desc -> unsorted
  let progressHeader = window.document.querySelector('#browse-table th[data-sort="progress"]');
  progressHeader.click();
  await wait(100);
  rows = window.document.querySelectorAll("#browse-table tbody tr");
  check(
    "progress header ascending",
    rows[0].textContent.includes("MTEEyeOfHarmony"),
    rows[0].textContent,
  );
  check(
    "ascending uses down arrow",
    window.document.querySelector('#browse-table th[data-sort="progress"]').textContent.includes("↓"),
  );
  progressHeader = window.document.querySelector('#browse-table th[data-sort="progress"]');
  progressHeader.click();
  await wait(100);
  rows = window.document.querySelectorAll("#browse-table tbody tr");
  check(
    "progress header descending",
    rows[0].textContent.includes("DynamicProbeClass"),
    rows[0].textContent,
  );
  check(
    "descending uses up arrow",
    window.document.querySelector('#browse-table th[data-sort="progress"]').textContent.includes("↑"),
  );
  progressHeader = window.document.querySelector('#browse-table th[data-sort="progress"]');
  progressHeader.click();
  await wait(100);
  rows = window.document.querySelectorAll("#browse-table tbody tr");
  check(
    "progress header unsorted returns original order",
    rows[0].textContent.includes("DynamicProbeClass") && rows[1].textContent.includes("MTEEyeOfHarmony"),
  );

  rows[0].dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await wait(250);
  check(
    "entry detail rendered",
    window.document.getElementById("detail-pos").textContent.includes("DynamicProbeClass") &&
      window.document.getElementById("detail-body").textContent.includes("progress"),
  );

  // language switch must re-render static labels, dynamic world count, status and tabs
  window.document.getElementById("lang-toggle").click();
  await wait(400);
  check(
    "language switch translates tabs",
    window.document.querySelector('[data-tab="browse"]').textContent.trim() === "Machines",
  );
  check(
    "language switch translates world count",
    window.document.getElementById("worlds-message").textContent.includes("worlds/backups"),
  );
  check(
    "language switch translates scan status",
    window.document.getElementById("browse-status").textContent.includes("Scan finished"),
  );

  // theme toggle should not be overwritten by the language switch
  window.document.getElementById("theme-toggle").click();
  await wait(100);
  const theme = window.document.body.getAttribute("data-theme");
  check("theme toggle works", theme === "dark" || theme === "light", String(theme));

  const snapTab = window.document.querySelector('[data-tab="snapshots"]');
  snapTab.click();
  await wait(200);
  check(
    "snapshot option rendered",
    window.document.querySelectorAll("#snap-a option").length >= 1,
  );

  // R1: editable datalist, manual reconnect is required after changing a filter.
  window.document.querySelector('[data-tab="live"]').click();
  await wait(100);
  check(
    "built-in machine classes available",
    [...window.document.querySelectorAll("#live-machine-options option")].some(
      (option) => option.value === "MTEEyeOfHarmony",
    ),
  );
  window.document.getElementById("live-machine").value = "MTEEyeOfHarmony";
  window.document.getElementById("live-connect").click();
  await wait(500);
  check("live connect sends selected class", connectCalls[0]?.machine === "MTEEyeOfHarmony");
  window.document.getElementById("live-machine").value = "NoSuchMachineManual";
  window.document.getElementById("live-machine").dispatchEvent(
    new window.Event("input", { bubbles: true }),
  );
  await wait(1400);
  check("filter change does not auto-connect", connectCalls.length === 1);
  window.document.getElementById("live-connect").click();
  await wait(500);
  check(
    "manual connect applies unmatched class",
    connectCalls.length >= 2 && connectCalls[connectCalls.length - 1].machine === "NoSuchMachineManual",
  );
} catch (error) {
  failures.push("exception: " + error);
  console.error(error);
}

check("no runtime JS errors", errors.length === 0, errors.join("; "));
console.log(failures.length ? `\n${failures.length} frontend check(s) failed` : "\nall frontend checks passed");
process.exit(failures.length ? 1 : 0);
