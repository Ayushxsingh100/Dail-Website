// The live-mode bridge: talks to the Web Worker that runs DAIL (dail-worker.js).
// Every call passes and returns JSON; nothing here decides anything.

const NOT_SECURE = "Live mode needs a secure page (https or 127.0.0.1) to check the bundled files.";

export async function bundleInfo(vendor = "vendor") {
  const response = await fetch(`${vendor}/files.json`, { cache: "no-cache" });
  if (!response.ok) throw new Error(`vendor/files.json: HTTP ${response.status}`);
  const listing = await response.json();
  return { listing, bytes: listing.size + listing.pyodide.size };
}

// onProgress({stage, done, total}) while loading; onEvent(name) for each audit event DAIL commits.
export function loadDail({ vendor = "vendor", onProgress = () => {}, onEvent = () => {} } = {}) {
  if (!globalThis.crypto || !crypto.subtle) return Promise.reject(new Error(NOT_SECURE));
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("./dail-worker.js", import.meta.url), { type: "module" });
    const waiting = new Map();
    let next = 1;
    const call = (name, ...args) => new Promise((answer) => {
      const id = next++;
      waiting.set(id, answer);
      worker.postMessage({ type: "call", id, name, args });
    });
    worker.onerror = (event) => {
      event.preventDefault();
      const error = event.message || "the worker stopped";
      reject(new Error(error));
      for (const answer of waiting.values()) answer({ ok: false, error });
      waiting.clear();
    };
    worker.onmessage = ({ data }) => {
      if (data.type === "progress") onProgress(data);
      else if (data.type === "event") onEvent(data.name);
      else if (data.type === "loaded") resolve({ ...data.info, call });
      else if (data.type === "failed") {
        worker.terminate();
        reject(new Error(data.error));
      } else if (data.type === "answer") {
        waiting.get(data.id)(data.answer);
        waiting.delete(data.id);
      }
    };
    worker.postMessage({ type: "load", vendor: new URL(`${vendor}/`, document.baseURI).href });
  });
}
