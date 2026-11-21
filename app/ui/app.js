(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const state = {
    file: null, currentZip: null, currentPackage: null, currentSubmission: null,
    health: null, configs: [], resultPollIntervalSeconds: 5, resultPollMaxWaitSeconds: 900,
  };

  const prettyBytes = (bytes) => {
    if (!Number.isFinite(bytes) || bytes < 0) return "—";
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KB", "MB", "GB"];
    let value = bytes / 1024;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
    return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[unit]}`;
  };

  const safeText = (value) => String(value ?? "").replace(/[\u0000-\u001f\u007f]/g, " ").trim();
  const displayId = (id) => id ? `${id.slice(0, 8)}…${id.slice(-5)}` : "Not returned";
  const dateLabel = (iso) => {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium", timeStyle: "short",
    }).format(date);
  };

  function toast(message) {
    const node = $("#toast");
    node.textContent = message;
    node.classList.add("show");
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(() => node.classList.remove("show"), 2600);
  }

  function navigate(page) {
    const selected = document.getElementById(`page-${page}`) ? page : "dashboard";
    $$(".page").forEach((section) => section.classList.toggle("active", section.id === `page-${selected}`));
    $$(".nav-item[data-page]").forEach((item) => item.classList.toggle("active", item.dataset.page === selected));
    const labels = { dashboard: "Dashboard", upload: "Upload & process", package: "Processed package" };
    $("#breadcrumbCurrent").textContent = labels[selected] || "Dashboard";
    document.title = `PDFLens · ${labels[selected] || "Dashboard"}`;
    if (selected === "package") renderPackage();
    $("#sidebar").classList.remove("open");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function checkHealth() {
    const dot = $("#connectionDot");
    const label = $("#connectionText");
    label.textContent = "Checking service";
    dot.className = "connection-dot";
    try {
      const response = await fetch("/ui-api/health", { headers: { Accept: "application/json" }, cache: "no-store" });
      const data = await response.json();
      if (!response.ok || data.available !== true) throw new Error("PDFLens is not responding.");
      state.health = true;
      dot.className = "connection-dot online";
      label.textContent = "Service available";
    } catch {
      state.health = false;
      dot.className = "connection-dot offline";
      label.textContent = "Service unavailable";
    }
  }

  function setFile(file) {
    clearFileError();
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf") && file.type !== "application/pdf") {
      showFileError("Choose a PDF file to continue.");
      return;
    }
    state.file = file;
    $("#dropzone").classList.add("hidden");
    $("#selectedFile").classList.remove("hidden");
    $("#fileName").textContent = safeText(file.name) || "Selected PDF";
    $("#fileSize").textContent = prettyBytes(file.size);
    $("#submitButton").disabled = !$("#configId").value;
  }

  function clearFileError() {
    $("#fileError").classList.add("hidden");
    $("#fileError").textContent = "";
  }

  function showFileError(message) {
    $("#fileError").textContent = message;
    $("#fileError").classList.remove("hidden");
  }

  function resetFile() {
    state.file = null;
    $("#pdfFile").value = "";
    $("#dropzone").classList.remove("hidden");
    $("#selectedFile").classList.add("hidden");
    $("#submitButton").disabled = true;
    clearFileError();
  }

  function extractionOptions() {
    return Object.fromEntries($$("#optionGrid input").map((input) => [input.value, input.checked]));
  }

  function safeError(data, status) {
    if (typeof data?.detail === "string") return safeText(data.detail);
    const code = safeText(data?.detail?.code);
    return code
      ? `PDFLens returned ${code}. Check the service logs or API owner for details.`
      : status === 0
        ? "The application backend could not be reached. Check your connection and try again."
        : `The request could not be completed (HTTP ${status}). Try again or contact the administrator.`;
  }

  async function loadConfigurations() {
    const select = $("#configId");
    const help = $("#configHelp");
    try {
      const response = await fetch("/ui-api/configurations", { headers: { Accept: "application/json" }, cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error("Configuration could not be loaded.");
      state.configs = Array.isArray(data.configurations) ? data.configurations : [];
      if (Number.isFinite(data.result_poll_interval_seconds) && data.result_poll_interval_seconds > 0) {
        state.resultPollIntervalSeconds = data.result_poll_interval_seconds;
      }
      if (Number.isFinite(data.result_poll_max_wait_seconds) && data.result_poll_max_wait_seconds > 0) {
        state.resultPollMaxWaitSeconds = data.result_poll_max_wait_seconds;
      }
      select.replaceChildren();
      if (!state.configs.length) {
        select.add(new Option("No configurations are configured", ""));
        help.textContent = "Ask the administrator to configure PDFLENS_CONFIGS_JSON in the environment file.";
      } else {
        select.add(new Option("Choose a configuration", ""));
        state.configs.forEach((config) => select.add(new Option(config.label, config.id)));
        help.textContent = "Configuration choices are managed in the application environment file.";
      }
      $("#callbackHelp").textContent = data.callback_configured
        ? "Callback URL: configured by the administrator."
        : "Callback URL: not configured (optional).";
    } catch {
      select.replaceChildren(new Option("Configuration unavailable", ""));
      help.textContent = "Check the application environment configuration.";
    }
    $("#submitButton").disabled = !state.file || !select.value;
  }

  function responseFilename(disposition, fallback) {
    if (!disposition) return fallback;
    const utf = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const simple = disposition.match(/filename="?([^";]+)"?/i);
    try { return decodeURIComponent(utf?.[1] || simple?.[1] || fallback); }
    catch { return fallback; }
  }

  async function readZipDirectory(blob) {
    const buffer = await blob.arrayBuffer();
    const view = new DataView(buffer);
    const bytes = new Uint8Array(buffer);
    const min = Math.max(0, bytes.length - 65_557);
    let eocd = -1;
    for (let offset = bytes.length - 22; offset >= min; offset -= 1) {
      if (view.getUint32(offset, true) === 0x06054b50) { eocd = offset; break; }
    }
    if (eocd < 0) throw new Error("The response was not a readable ZIP archive.");
    const count = view.getUint16(eocd + 10, true);
    const directorySize = view.getUint32(eocd + 12, true);
    let offset = view.getUint32(eocd + 16, true);
    if (count > 2000 || offset + directorySize > bytes.length) throw new Error("The ZIP directory is invalid or exceeds the supported inventory limit.");
    const decoder = new TextDecoder("utf-8", { fatal: false });
    const files = [];
    let totalUncompressed = 0;
    for (let index = 0; index < count; index += 1) {
      if (offset + 46 > bytes.length || view.getUint32(offset, true) !== 0x02014b50) {
        throw new Error("The ZIP directory contains an invalid entry.");
      }
      const flags = view.getUint16(offset + 8, true);
      const compressedSize = view.getUint32(offset + 20, true);
      const size = view.getUint32(offset + 24, true);
      const nameLength = view.getUint16(offset + 28, true);
      const extraLength = view.getUint16(offset + 30, true);
      const commentLength = view.getUint16(offset + 32, true);
      const next = offset + 46 + nameLength + extraLength + commentLength;
      if (next > bytes.length) throw new Error("The ZIP directory contains an incomplete entry.");
      const decoderForName = flags & 0x0800 ? decoder : new TextDecoder("windows-1252");
      const name = safeText(decoderForName.decode(bytes.subarray(offset + 46, offset + 46 + nameLength)));
      offset = next;
      if (!name || name.endsWith("/")) continue;
      const segments = name.replaceAll("\\", "/").split("/");
      if (name.startsWith("/") || segments.includes("..") || /^[A-Za-z]:/.test(name)) {
        throw new Error("The ZIP contains a path that cannot be safely displayed.");
      }
      totalUncompressed += size;
      if (totalUncompressed > 500 * 1024 * 1024) throw new Error("The ZIP inventory exceeds the supported size limit.");
      if (size > 0 && (compressedSize === 0 || size / compressedSize > 1000)) {
        throw new Error("The ZIP contains an entry with an unsafe compression ratio.");
      }
      files.push({ name, size, type: name.includes(".") ? name.split(".").pop().toUpperCase() : "FILE" });
    }
    return files;
  }

  function artifactCategory(name) {
    const path = name.toLowerCase();
    const ext = path.split(".").pop();
    if (["pdf", "docx"].includes(ext)) return "Document";
    if (ext === "json") return "Metadata";
    if (["png", "jpg", "jpeg", "webp", "gif", "tif", "tiff"].includes(ext)) {
      return /table/i.test(path) || path.includes("/tables/") ? "Table snapshot" : "Image asset";
    }
    return "Other file";
  }

  async function submit() {
    if (!state.file || !$("#configId").value) return;
    $("#submitError").classList.add("hidden");
    $("#submissionSuccess").classList.add("hidden");
    $("#resultPollingError").classList.add("hidden");
    $("#progressCard").classList.remove("hidden");
    $("#submitButton").disabled = true;
    const body = new FormData();
    body.append("file", state.file, state.file.name);
    body.append("config_id", $("#configId").value);
    for (const [name, value] of Object.entries(extractionOptions())) body.append(name, String(value));
    const started = new Date().toISOString();
    let requestId = "";
    try {
      const response = await fetch("/ui-api/jobs", { method: "POST", body });
      let data = {};
      try { data = await response.json(); } catch { /* do not expose raw server response */ }
      if (!response.ok) {
        requestId = safeText(data?.detail?.request_id);
        throw Object.assign(new Error(safeError(data, response.status)), { requestId, httpStatus: response.status });
      }
      requestId = safeText(data.request_id);
      if (!requestId || data.status === undefined) throw new Error("PDFLens returned an incomplete submission response.");
      const record = {
        filename: safeText(data.filename || state.file.name), requestId,
        submittedAt: data.submitted_at || started, outcome: "submitted",
        statusText: String(data.status), config: safeText(data.config_label || $("#configId option:checked").textContent),
        size: state.file.size, callbackConfigured: Boolean(data.callback_configured),
        extractionOptions: extractionOptions(),
      };
      state.currentSubmission = record;
      $("#submissionStatus").textContent = safeText(record.statusText);
      $("#submissionRequestId").textContent = requestId;
      $("#submissionSuccess").classList.remove("hidden");
      toast("PDFLens accepted the request.");
      resetFile();
    } catch (error) {
      const message = error.message || "The request could not be completed.";
      $("#submitErrorMessage").textContent = message;
      const failedRequestId = error.requestId || requestId;
      $("#submitErrorId").textContent = failedRequestId ? `Request ID: ${failedRequestId}` : "";
      $("#submitError").classList.remove("hidden");
    } finally {
      $("#progressCard").classList.add("hidden");
      $("#submitButton").disabled = !state.file || !$("#configId").value;
    }
  }

  async function retrieveResult(record, trigger = null) {
    if (!record?.requestId) return;
    const originalLabel = trigger?.textContent;
    if (trigger) { trigger.disabled = true; trigger.textContent = "Requesting…"; }
    const pollingCard = $("#resultPollingCard");
    const pollingText = $("#resultPollingText");
    const pollingFootprint = $("#resultPollingFootprint");
    const pollError = $("#resultPollingError");
    const started = Date.now();
    let attempt = 0;
    let receivedZip = false;
    pollError.classList.add("hidden");
    pollingCard.classList.remove("hidden");
    pollingText.textContent = `Checking PDFLens every ${state.resultPollIntervalSeconds} seconds for up to ${Math.ceil(state.resultPollMaxWaitSeconds / 60)} minutes.`;
    pollingFootprint.textContent = `Request ID: ${record.requestId}`;
    const elapsedTimer = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - started) / 1000);
      pollingFootprint.textContent = `Attempt ${attempt || 1} · elapsed ${elapsed}s of ${state.resultPollMaxWaitSeconds}s · request ${record.requestId}`;
    }, 1000);
    toast("Checking whether PDFLens has finished processing…");
    try {
      while ((Date.now() - started) / 1000 < state.resultPollMaxWaitSeconds) {
        attempt += 1;
        pollingText.textContent = `Checking PDFLens result (attempt ${attempt})…`;
        pollingFootprint.textContent = `Request ID: ${record.requestId}`;
        const remainingMs = Math.max(1, state.resultPollMaxWaitSeconds * 1000 - (Date.now() - started));
        const controller = new AbortController();
        const abortTimer = window.setTimeout(() => controller.abort(), remainingMs);
        let response;
        try {
          response = await fetch("/ui-api/results", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/zip, application/json" },
            body: JSON.stringify({ request_id: record.requestId, attempt }),
            signal: controller.signal,
          });
        } catch (error) {
          if (controller.signal.aborted) throw new Error(`Stopped checking after ${state.resultPollMaxWaitSeconds} seconds. The request may still be processing; retry with the same request ID.`);
          throw error;
        } finally {
          window.clearTimeout(abortTimer);
        }

        if (response.status === 202) {
          let data = {};
          try { data = await response.json(); } catch { /* use generic queued status */ }
          const upstreamStatus = safeText(data.status || "processing");
          const elapsed = Math.floor((Date.now() - started) / 1000);
          pollingText.textContent = `PDFLens status: ${upstreamStatus}. Checking again in ${state.resultPollIntervalSeconds} seconds.`;
          pollingFootprint.textContent = `Attempt ${attempt} · elapsed ${elapsed}s · request ${record.requestId}`;
          const sleepMs = Math.min(state.resultPollIntervalSeconds * 1000, Math.max(0, state.resultPollMaxWaitSeconds * 1000 - (Date.now() - started)));
          if (sleepMs > 0) await new Promise((resolve) => window.setTimeout(resolve, sleepMs));
          continue;
        }
        if (!response.ok) {
          let data = {};
          try { data = await response.json(); } catch { /* show a generic safe message */ }
          throw new Error(safeError(data, response.status));
        }
        if (!(response.headers.get("Content-Type") || "").toLowerCase().includes("application/zip")) {
          throw new Error("PDFLens did not return a ZIP package.");
        }
        const zip = await response.blob();
        const files = await readZipDirectory(zip);
        const fallback = `${record.filename.replace(/\.pdf$/i, "") || "pdflens-result"}.zip`;
        const packageRecord = {
          ...record,
          packageName: responseFilename(response.headers.get("Content-Disposition"), fallback),
          packageBytes: zip.size,
          files,
          retrievedAt: new Date().toISOString(),
        };
        state.currentZip = zip;
        state.currentPackage = packageRecord;
        renderPackage();
        downloadBlob(zip, packageRecord.packageName);
        navigate("package");
        toast(`Result ZIP retrieved after ${attempt} check${attempt === 1 ? "" : "s"}.`);
        receivedZip = true;
        break;
      }
      if (!receivedZip) throw new Error(`PDFLens was still processing after ${state.resultPollMaxWaitSeconds} seconds. Keep request ID ${record.requestId} and retry result retrieval later.`);
    } catch (error) {
      const message = error.message || "Could not retrieve this result. Check availability and try again.";
      $("#resultPollingErrorText").textContent = message;
      $("#resultPollingErrorId").textContent = `Request ID: ${record.requestId}`;
      pollError.classList.remove("hidden");
      toast(message);
    } finally {
      window.clearInterval(elapsedTimer);
      pollingCard.classList.add("hidden");
      if (trigger) { trigger.disabled = false; trigger.textContent = originalLabel; }
    }
  }

  function downloadBlob(blob, name) {
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_") || "pdflens-result.zip";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  }

  function renderPackage() {
    const record = state.currentPackage;
    const loaded = Boolean(record?.files);
    $("#packageEmpty").classList.toggle("hidden", loaded);
    $("#packageContent").classList.toggle("hidden", !loaded);
    if (!loaded) return;
    $("#packageName").textContent = safeText(record.packageName);
    $("#packageRequest").textContent = record.requestId ? `Request ${displayId(record.requestId)}` : "Request ID not returned";
    $("#packageSize").textContent = prettyBytes(record.packageBytes);
    $("#packageTime").textContent = `Retrieved ${dateLabel(record.retrievedAt || record.submittedAt)}`;
    const categories = record.files.map((file) => artifactCategory(file.name));
    $("#packageFileCount").textContent = String(record.files.length);
    $("#packageDocuments").textContent = String(categories.filter((category) => category === "Document").length);
    $("#packageMetadata").textContent = String(categories.filter((category) => category === "Metadata").length);
    $("#packageAssets").textContent = String(categories.filter((category) => ["Image asset", "Table snapshot"].includes(category)).length);
    const tbody = $("#packageRows");
    tbody.replaceChildren();
    record.files.forEach((file) => {
      const tr = document.createElement("tr");
      const name = document.createElement("td");
      name.className = "file-name-cell";
      name.textContent = safeText(file.name);
      const type = document.createElement("td");
      type.className = "file-type";
      type.textContent = safeText(file.type);
      const size = document.createElement("td");
      size.textContent = prettyBytes(file.size);
      const category = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = "category-badge";
      badge.textContent = artifactCategory(file.name);
      category.append(badge);
      tr.append(name, type, size, category);
      tbody.append(tr);
    });
    $("#downloadAgain").onclick = () => {
      if (state.currentZip) downloadBlob(state.currentZip, record.packageName);
      else retrieveResult(record, $("#downloadAgain"));
    };
  }

  function setup() {
    $$('[data-page]').forEach((item) => item.addEventListener("click", (event) => {
      event.preventDefault();
      navigate(item.dataset.page);
    }));
    $$('[data-go]').forEach((button) => button.addEventListener("click", () => navigate(button.dataset.go)));
    $("#menuButton").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
    $("#refreshHealth").addEventListener("click", checkHealth);
    $("#pdfFile").addEventListener("change", (event) => setFile(event.target.files?.[0]));
    $("#configId").addEventListener("change", () => { $("#submitButton").disabled = !state.file || !$("#configId").value; });
    $("#removeFile").addEventListener("click", resetFile);
    $("#submitButton").addEventListener("click", submit);
    $("#retrieveSubmitted").addEventListener("click", (event) => retrieveResult(state.currentSubmission, event.currentTarget));
    $("#dropzone").addEventListener("dragover", (event) => { event.preventDefault(); $("#dropzone").classList.add("dragover"); });
    $("#dropzone").addEventListener("dragleave", () => $("#dropzone").classList.remove("dragover"));
    $("#dropzone").addEventListener("drop", (event) => {
      event.preventDefault();
      $("#dropzone").classList.remove("dragover");
      setFile(event.dataTransfer.files?.[0]);
    });
    checkHealth();
    loadConfigurations();
    navigate("dashboard");
  }

  document.addEventListener("DOMContentLoaded", setup, { once: true });
})();
