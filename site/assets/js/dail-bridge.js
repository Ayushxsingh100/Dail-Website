// The live-mode bridge: DAIL v1.0, unmodified, inside the visitor's browser (PLAN §3.8; D-20, D-22).
//
// loadDail() loads the self-hosted Pyodide runtime and its sqlite3 package from site/vendor/,
// fetches every bundled file listed in vendor/files.json, checks each file's SHA-256 before it is
// written into Pyodide's in-memory file system, and returns a handle on dail_demo.browser.Live.
// Every call passes and returns JSON text; nothing here decides anything.

const NOT_SECURE = "Live mode needs a secure page (https or 127.0.0.1) to check the bundled files.";

function hex(buffer) {
  return Array.from(new Uint8Array(buffer), (b) => b.toString(16).padStart(2, "0")).join("");
}

export async function bundleInfo(vendor = "vendor") {
  const response = await fetch(`${vendor}/files.json`, { cache: "no-cache" });
  if (!response.ok) throw new Error(`vendor/files.json: HTTP ${response.status}`);
  const listing = await response.json();
  return { listing, bytes: listing.size + listing.pyodide.size };
}

export async function loadDail({ vendor = "vendor", onProgress = () => {} } = {}) {
  if (!globalThis.crypto || !crypto.subtle) throw new Error(NOT_SECURE);
  const { listing, bytes } = await bundleInfo(vendor);
  const base = new URL(`${vendor}/${listing.pyodide.dir}/`, document.baseURI).href;
  onProgress({ stage: "runtime", done: 0, total: bytes });
  const { loadPyodide } = await import(`${base}pyodide.mjs`);
  const pyodide = await loadPyodide({ indexURL: base, lockFileURL: `${base}pyodide-lock.json` });
  onProgress({ stage: "sqlite3", done: listing.pyodide.size, total: bytes });
  await pyodide.loadPackage("sqlite3", { messageCallback: () => {}, errorCallback: () => {} });

  let done = listing.pyodide.size;
  const files = listing.files;
  const queue = files.slice();
  async function worker() {
    while (queue.length) {
      const file = queue.shift();
      const response = await fetch(`${vendor}/${file.path}`, { cache: "no-cache" });
      if (!response.ok) throw new Error(`${file.path}: HTTP ${response.status}`);
      const data = await response.arrayBuffer();
      const digest = hex(await crypto.subtle.digest("SHA-256", data));
      if (digest !== file.sha256) throw new Error(`${file.path}: SHA-256 ${digest} is not the bundled ${file.sha256}`);
      const target = `/vendor/${file.path}`;
      pyodide.FS.mkdirTree(target.slice(0, target.lastIndexOf("/")));
      pyodide.FS.writeFile(target, new Uint8Array(data));
      done += file.size;
      onProgress({ stage: "files", done, total: bytes });
    }
  }
  await Promise.all(Array.from({ length: 8 }, worker));

  pyodide.runPython("import sys\nsys.path[0:0] = ['/vendor/dail_live', '/vendor/dail']\n");
  const browser = pyodide.pyimport("dail_demo.browser");
  const live = browser.Live("/vendor", "/work");
  onProgress({ stage: "ready", done: bytes, total: bytes });

  function call(name, ...args) {
    try {
      return { ok: true, value: JSON.parse(live[name](...args)) };
    } catch (error) {
      // a Python exception: its last line is the one-line reason (never a key: the site has none)
      const text = String(error && error.message ? error.message : error).trim().split("\n");
      return { ok: false, error: text[text.length - 1] };
    }
  }
  return { pyodide, bytes, files: files.length, call };
}
