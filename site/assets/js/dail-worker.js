// Live mode's Web Worker: DAIL v1.0, unmodified, under self-hosted Pyodide (PLAN §3.8; D-20, D-22, D-29).
//
// It loads Pyodide and its sqlite3 package from vendor/, fetches every file listed in
// vendor/files.json, checks its SHA-256 before writing it into Pyodide's in-memory file system, and
// then answers calls on dail_demo.browser.Live with JSON text. While DAIL evaluates, each audit event
// DAIL commits is posted to the page as it happens. Nothing here decides anything.

let pyodide = null;
let live = null;

function hex(buffer) {
  return Array.from(new Uint8Array(buffer), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function load(vendor) {
  const response = await fetch(`${vendor}files.json`, { cache: "no-cache" });
  if (!response.ok) throw new Error(`vendor/files.json: HTTP ${response.status}`);
  const listing = await response.json();
  const bytes = listing.size + listing.pyodide.size;
  const progress = (stage, done) => postMessage({ type: "progress", stage, done, total: bytes });
  const base = `${vendor}${listing.pyodide.dir}/`;
  progress("runtime", 0);
  const { loadPyodide } = await import(`${base}pyodide.mjs`);
  pyodide = await loadPyodide({ indexURL: base, lockFileURL: `${base}pyodide-lock.json` });
  progress("sqlite3", listing.pyodide.size);
  await pyodide.loadPackage("sqlite3", { messageCallback: () => {}, errorCallback: () => {} });

  let done = listing.pyodide.size;
  const queue = listing.files.slice();
  async function fetchFiles() {
    while (queue.length) {
      const file = queue.shift();
      const answer = await fetch(`${vendor}${file.path}`, { cache: "no-cache" });
      if (!answer.ok) throw new Error(`${file.path}: HTTP ${answer.status}`);
      const data = await answer.arrayBuffer();
      const digest = hex(await crypto.subtle.digest("SHA-256", data));
      if (digest !== file.sha256) throw new Error(`${file.path}: SHA-256 ${digest} is not the bundled ${file.sha256}`);
      const target = `/vendor/${file.path}`;
      pyodide.FS.mkdirTree(target.slice(0, target.lastIndexOf("/")));
      pyodide.FS.writeFile(target, new Uint8Array(data));
      done += file.size;
      progress("files", done);
    }
  }
  await Promise.all(Array.from({ length: 8 }, fetchFiles));

  pyodide.runPython("import sys\nsys.path[0:0] = ['/vendor/dail_live', '/vendor/dail']\n");
  live = pyodide.pyimport("dail_demo.browser").Live("/vendor", "/work");
  live.listen((name) => postMessage({ type: "event", name }));
  const python = pyodide.runPython("import sys, sqlite3\nf'{sys.version} | sqlite {sqlite3.sqlite_version}'");
  progress("ready", bytes);
  return { bytes, files: listing.files.length, python };
}

function call(name, args) {
  try {
    return { ok: true, value: JSON.parse(live[name](...args)) };
  } catch (error) {
    // a Python exception: its last line is the one-line reason (the site holds no key)
    const lines = String(error && error.message ? error.message : error).trim().split("\n");
    return { ok: false, error: lines[lines.length - 1] };
  }
}

onmessage = async ({ data }) => {
  if (data.type === "load") {
    try {
      postMessage({ type: "loaded", info: await load(data.vendor) });
    } catch (error) {
      postMessage({ type: "failed", error: String(error.message || error) });
    }
    return;
  }
  postMessage({ type: "answer", id: data.id, answer: call(data.name, data.args) });
};
