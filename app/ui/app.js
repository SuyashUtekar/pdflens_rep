(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const state = {
    file: null, currentZip: null, currentPackage: null, currentSubmission: null,
    health: null, configConfigured: false, previewObjectUrl: null,
    pageCount: null, pageCountAvailable: false, pageCountPending: false, pageInfoRequest: 0,
    resultPollIntervalSeconds: 5, resultPollMaxWaitSeconds: 900, resultPolling: false, webhookSource: null,
    comparePage: 1, compareMetadata: null, compareMetadataPromise: null,
    compareDocxPages: null, compareDocxParagraphs: null, compareDocxUsesBookmarks: false, compareDocxPromise: null,
    comparePdfUrl: null, comparePdfUrls: new Set(), compareAssetUrls: [], compareRenderId: 0, comparePageRenderId: 0,
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
    const labels = { dashboard: "Dashboard", upload: "Upload & process", package: "Processed package", validation: "Comparison & validation" };
    $("#breadcrumbCurrent").textContent = labels[selected] || "Dashboard";
    document.title = `PDFLens · ${labels[selected] || "Dashboard"}`;
    if (selected === "package") renderPackage();
    if (selected === "validation") renderPageComparison();
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
    state.pageCount = null;
    state.pageCountAvailable = false;
    state.pageCountPending = true;
    $("#startPage").value = "";
    $("#endPage").value = "";
    $("#startPage").disabled = true;
    $("#endPage").disabled = true;
    $("#pageRangeError").classList.add("hidden");
    $("#pdfPageCount").textContent = "Reading the PDF page count…";
    $("#dropzone").classList.add("hidden");
    $("#selectedFile").classList.remove("hidden");
    $("#fileName").textContent = safeText(file.name) || "Selected PDF";
    $("#fileSize").textContent = prettyBytes(file.size);
    $("#submitButton").disabled = true;
    inspectPdfPageCount(file);
  }

  async function inspectPdfPageCount(file) {
    const requestId = ++state.pageInfoRequest;
    const body = new FormData();
    body.append("file", file, file.name);
    try {
      const response = await fetch("/ui-api/pdf-info", { method: "POST", body });
      const data = await response.json();
      if (!response.ok) throw new Error(safeError(data, response.status));
      if (requestId !== state.pageInfoRequest || state.file !== file) return;
      const count = Number(data.page_count);
      if (data.page_count_available === true && Number.isInteger(count) && count > 0) {
        state.pageCount = count;
        state.pageCountAvailable = true;
        $("#startPage").max = String(count);
        $("#endPage").max = String(count);
        $("#startPage").disabled = false;
        $("#endPage").disabled = false;
        $("#pdfPageCount").textContent = `PDF contains ${count} pages. Valid range: 1–${count}.`;
      } else {
        $("#pdfPageCount").textContent = "Page count could not be read. You can process the full PDF; page-range selection is unavailable.";
      }
    } catch (error) {
      if (requestId !== state.pageInfoRequest || state.file !== file) return;
      $("#pdfPageCount").textContent = error.message || "Page count could not be read. You can still process the full PDF.";
    } finally {
      if (requestId === state.pageInfoRequest && state.file === file) {
        state.pageCountPending = false;
        $("#submitButton").disabled = !state.file || !state.configConfigured || state.pageCountPending;
      }
    }
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
    state.pageInfoRequest += 1;
    state.pageCount = null;
    state.pageCountAvailable = false;
    state.pageCountPending = false;
    state.file = null;
    $("#pdfFile").value = "";
    $("#startPage").value = "";
    $("#endPage").value = "";
    $("#startPage").max = "";
    $("#endPage").max = "";
    $("#startPage").disabled = true;
    $("#endPage").disabled = true;
    $("#pdfPageCount").textContent = "Select a PDF to see its page count.";
    $("#pageRangeError").classList.add("hidden");
    $("#dropzone").classList.remove("hidden");
    $("#selectedFile").classList.add("hidden");
    $("#submitButton").disabled = true;
    clearFileError();
  }

  function extractionOptions() {
    return Object.fromEntries($$("#optionGrid input").map((input) => [input.value, input.checked]));
  }

  function selectedPageRange() {
    const startText = $("#startPage").value.trim();
    const endText = $("#endPage").value.trim();
    if (!startText && !endText) return { start: null, end: null, error: "" };
    if (!startText || !endText) return { start: null, end: null, error: "Enter both a start page and an end page, or leave both blank." };
    if (!state.pageCountAvailable || !state.pageCount) {
      return { start: null, end: null, error: "The PDF page count could not be verified, so a page range cannot be selected." };
    }
    const start = Number(startText);
    const end = Number(endText);
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < 1) {
      return { start: null, end: null, error: "Page numbers must be whole numbers starting at 1." };
    }
    if (start > end) return { start: null, end: null, error: "Start page must be less than or equal to end page." };
    if (start > state.pageCount || end > state.pageCount) {
      return { start: null, end: null, error: `Page numbers cannot exceed this PDF's ${state.pageCount}-page limit.` };
    }
    return { start, end, error: "" };
  }

  function recordRequestAudit(record, status, detail, attempt = null) {
    if (!record) return;
    record.auditTrail ||= [];
    record.auditTrail.push({ status: safeText(status) || "Status update", detail: safeText(detail), attempt, timestamp: new Date().toISOString() });
    renderRequestAudit(record);
  }

  function renderRequestAudit(record) {
    if (!record?.requestId) return;
    for (const panel of $$('[data-request-audit]')) {
      panel.classList.remove("hidden");
      panel.querySelector(".audit-request-id").textContent = record.requestId;
      const events = panel.querySelector(".audit-events");
      events.replaceChildren();
      for (const event of record.auditTrail || []) {
        const item = document.createElement("li");
        item.className = "audit-event";
        const header = document.createElement("div");
        header.className = "audit-event-header";
        const status = document.createElement("b");
        status.textContent = event.status;
        const timestamp = document.createElement("time");
        timestamp.dateTime = event.timestamp;
        timestamp.textContent = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "medium" }).format(new Date(event.timestamp));
        header.append(status, timestamp);
        item.append(header);
        if (event.detail) {
          const detail = document.createElement("p");
          detail.textContent = event.detail;
          item.append(detail);
        }
        if (event.attempt !== null && event.attempt !== undefined) {
          const attempt = document.createElement("small");
          attempt.textContent = `Check attempt ${event.attempt}`;
          item.append(attempt);
        }
        events.append(item);
      }
    }
  }

  function webhookStatusKind(status) {
    const normalized = String(status || "").toLowerCase().replace(/[\s-]+/g, "_");
    if (/fail|error|reject|cancel|expired|dead_letter/.test(normalized)) return "failed";
    if (/not_complete|not_completed|not_success|not_ready|not_available/.test(normalized)) return "pending";
    if (/complete|success|succeed|finished|(^|_)done($|_)|result_ready|(^|_)ready($|_)/.test(normalized)) return "complete";
    if (/queue|pending|process|in_progress|running|accepted|submitted|started/.test(normalized)) return "pending";
    return "unknown";
  }

  function listenForPdfLensWebhook(record) {
    if (!record?.webhookEnabled || typeof EventSource === "undefined") return;
    state.webhookSource?.close();
    const source = new EventSource(`/ui-api/webhook-events/${encodeURIComponent(record.requestId)}`);
    state.webhookSource = source;
    source.addEventListener("status", (message) => {
      if (state.currentSubmission !== record) return;
      let event;
      try { event = JSON.parse(message.data); } catch { return; }
      const status = safeText(event.status || "Status update");
      recordRequestAudit(record, status, safeText(event.message) || "Status update received from the PDFLens webhook.");
      $("#submissionStatus").textContent = status;
      const kind = webhookStatusKind(status);
      if (kind === "failed") {
        source.close();
        if (state.webhookSource === source) state.webhookSource = null;
        recordRequestAudit(record, "Processing failed", "PDFLens reported a terminal failure status.");
        return;
      }
      if (kind === "complete" && !record.webhookResultRequested) {
        record.webhookResultRequested = true;
        retrieveResult(record, null, { singleAttempt: true, triggeredByWebhook: true });
      }
    });
    source.onerror = () => {
      if (state.currentSubmission !== record || record.webhookConnectionIssueRecorded) return;
      record.webhookConnectionIssueRecorded = true;
      recordRequestAudit(record, "Webhook connection issue", "The live callback stream disconnected. It will reconnect; you can also check the result once manually.");
    };
  }

  function handlePageRangeInput(event) {
    const input = event.currentTarget;
    const error = $("#pageRangeError");
    const value = Number(input.value);
    if (input.value && state.pageCountAvailable && value > state.pageCount) {
      input.value = String(state.pageCount);
      error.textContent = `This PDF has ${state.pageCount} pages. The value was limited to page ${state.pageCount}.`;
      error.classList.remove("hidden");
      return;
    }
    error.textContent = "";
    error.classList.add("hidden");
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

  async function loadUiSettings() {
    try {
      const response = await fetch("/ui-api/settings", { headers: { Accept: "application/json" }, cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error("UI settings could not be loaded.");
      state.configConfigured = data.configured === true && data.file_manager_configured === true;
      if (Number.isFinite(data.result_poll_interval_seconds) && data.result_poll_interval_seconds > 0) {
        state.resultPollIntervalSeconds = data.result_poll_interval_seconds;
      }
      if (Number.isFinite(data.result_poll_max_wait_seconds) && data.result_poll_max_wait_seconds > 0) {
        state.resultPollMaxWaitSeconds = data.result_poll_max_wait_seconds;
      }
    } catch {
      state.configConfigured = false;
    }
    $("#submitButton").disabled = !state.file || !state.configConfigured || state.pageCountPending;
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
      const compressionMethod = view.getUint16(offset + 10, true);
      const compressedSize = view.getUint32(offset + 20, true);
      const size = view.getUint32(offset + 24, true);
      const nameLength = view.getUint16(offset + 28, true);
      const extraLength = view.getUint16(offset + 30, true);
      const commentLength = view.getUint16(offset + 32, true);
      const localHeaderOffset = view.getUint32(offset + 42, true);
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
      files.push({
        name, size, compressedSize, compressionMethod, localHeaderOffset, flags,
        type: name.includes(".") ? name.split(".").pop().toUpperCase() : "FILE",
      });
    }
    return files;
  }

  async function readZipEntry(blob, entry) {
    if (!blob || !entry) throw new Error("The package file is no longer available in this page session.");
    if (entry.flags & 0x0001) throw new Error("This ZIP entry is encrypted and cannot be previewed here.");
    const headerBuffer = await blob.slice(entry.localHeaderOffset, entry.localHeaderOffset + 30).arrayBuffer();
    const header = new DataView(headerBuffer);
    if (header.byteLength < 30 || header.getUint32(0, true) !== 0x04034b50) {
      throw new Error("The selected file has an invalid ZIP local header.");
    }
    const nameLength = header.getUint16(26, true);
    const extraLength = header.getUint16(28, true);
    const dataOffset = entry.localHeaderOffset + 30 + nameLength + extraLength;
    const compressed = blob.slice(dataOffset, dataOffset + entry.compressedSize);
    let result;
    if (entry.compressionMethod === 0) {
      result = compressed;
    } else if (entry.compressionMethod === 8 && typeof DecompressionStream !== "undefined") {
      try {
        const stream = compressed.stream().pipeThrough(new DecompressionStream("deflate-raw"));
        result = await new Response(stream).blob();
      } catch {
        throw new Error("This browser cannot decompress this ZIP entry. Download the ZIP to open it.");
      }
    } else {
      throw new Error("This file uses a ZIP compression method this browser cannot preview. Download the ZIP instead.");
    }
    if (result.size !== entry.size) throw new Error("The selected file did not decompress to its expected size.");
    return result;
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

  function fileExtension(name) {
    const leaf = name.split(/[\\/]/).pop() || "";
    return leaf.includes(".") ? leaf.split(".").pop().toLowerCase() : "";
  }

  function canPreviewFile(file) {
    return ["pdf", "docx", "json", "txt", "md", "csv", "xml", "html", "htm", "png", "jpg", "jpeg", "webp", "gif", "svg", "tif", "tiff"].includes(fileExtension(file.name));
  }

  function createPackageFileRow(file, group = "") {
    const tr = document.createElement("tr");
    if (group) {
      tr.dataset.assetGroup = group;
      tr.hidden = true;
    }
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
    const actions = document.createElement("td");
    actions.className = "package-file-actions";
    if (canPreviewFile(file)) {
      const preview = document.createElement("button");
      preview.className = "button button-secondary package-action";
      preview.textContent = "Preview";
      preview.addEventListener("click", () => openFilePreview(file));
      actions.append(preview);
    }
    const download = document.createElement("button");
    download.className = "button button-secondary package-action";
    download.textContent = "Download";
    download.addEventListener("click", () => downloadPackageFile(file));
    actions.append(download);
    tr.append(name, type, size, category, actions);
    return tr;
  }

  function createAssetFolderRow(label, group, files) {
    const row = document.createElement("tr");
    row.className = "asset-folder-row";
    const cell = document.createElement("td");
    cell.colSpan = 5;
    const toggle = document.createElement("button");
    toggle.className = "asset-folder-toggle";
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", "false");
    const chevron = document.createElement("span");
    chevron.className = "asset-folder-chevron";
    chevron.setAttribute("aria-hidden", "true");
    chevron.textContent = "›";
    const icon = document.createElement("span");
    icon.className = "asset-folder-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "▰";
    const title = document.createElement("b");
    title.textContent = label;
    const count = document.createElement("small");
    count.textContent = `${files.length} ${files.length === 1 ? "file" : "files"}`;
    toggle.append(chevron, icon, title, count);
    toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(expanded));
      row.parentElement.querySelectorAll(`[data-asset-group="${group}"]`).forEach((fileRow) => {
        fileRow.hidden = !expanded;
      });
    });
    cell.append(toggle);
    row.append(cell);
    return row;
  }

  function mimeTypeFor(name) {
    const ext = fileExtension(name);
    return ({
      pdf: "application/pdf", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg",
      webp: "image/webp", gif: "image/gif", svg: "image/svg+xml", tif: "image/tiff", tiff: "image/tiff",
      json: "application/json", txt: "text/plain", md: "text/markdown", csv: "text/csv",
      xml: "application/xml", html: "text/plain", htm: "text/plain",
    })[ext] || "application/octet-stream";
  }

  function showPreviewError(message) {
    const box = document.createElement("div");
    box.className = "preview-error";
    box.textContent = message;
    $("#previewBody").replaceChildren(box);
  }

  function appendDocxParagraph(parent, paragraph, wordNamespace) {
    const styleNode = paragraph.getElementsByTagNameNS(wordNamespace, "pStyle")[0];
    const styleName = styleNode?.getAttributeNS(wordNamespace, "val") || styleNode?.getAttribute("w:val") || "";
    const headingLevel = Number(styleName.match(/heading\s*(\d)/i)?.[1] || styleName.match(/Heading(\d)/)?.[1] || 0);
    const tagName = headingLevel >= 1 && headingLevel <= 6 ? `h${headingLevel}` : "p";
    const element = document.createElement(tagName);
    for (const node of paragraph.getElementsByTagNameNS(wordNamespace, "t")) {
      element.append(document.createTextNode(node.textContent || ""));
    }
    if (element.textContent.trim()) parent.append(element);
  }

  async function renderDocxPreview(docxBlob, container) {
    const nestedFiles = await readZipDirectory(docxBlob);
    const documentEntry = nestedFiles.find((entry) => entry.name === "word/document.xml");
    if (!documentEntry) throw new Error("This DOCX does not contain its main document content.");
    const xmlText = await (await readZipEntry(docxBlob, documentEntry)).text();
    const xml = new DOMParser().parseFromString(xmlText, "application/xml");
    if (xml.querySelector("parsererror")) throw new Error("The DOCX document XML could not be read.");
    const wordNamespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
    const body = xml.getElementsByTagNameNS(wordNamespace, "body")[0];
    if (!body) throw new Error("This DOCX has no readable document body.");
    const preview = document.createElement("article");
    preview.className = "docx-preview";
    for (const child of body.children) {
      if (child.localName === "p") {
        appendDocxParagraph(preview, child, wordNamespace);
      } else if (child.localName === "tbl") {
        const table = document.createElement("table");
        table.className = "preview-docx-table";
        for (const row of child.getElementsByTagNameNS(wordNamespace, "tr")) {
          const tr = document.createElement("tr");
          for (const cell of row.getElementsByTagNameNS(wordNamespace, "tc")) {
            const td = document.createElement("td");
            for (const paragraph of cell.getElementsByTagNameNS(wordNamespace, "p")) {
              appendDocxParagraph(td, paragraph, wordNamespace);
            }
            tr.append(td);
          }
          table.append(tr);
        }
        preview.append(table);
      }
    }
    if (!preview.childNodes.length) throw new Error("No readable paragraphs or tables were found in the DOCX.");
    const note = document.createElement("p");
    note.className = "preview-note";
    note.textContent = "Text preview only. Download the DOCX to see its full Word layout and styling.";
    container.replaceChildren(note, preview);
  }

  function parseCsv(text) {
    const rows = [];
    let row = [];
    let cell = "";
    let quoted = false;
    for (let index = 0; index < text.length; index += 1) {
      const char = text[index];
      if (char === '"' && quoted && text[index + 1] === '"') { cell += '"'; index += 1; }
      else if (char === '"') quoted = !quoted;
      else if (char === "," && !quoted) { row.push(cell); cell = ""; }
      else if ((char === "\n" || char === "\r") && !quoted) {
        if (char === "\r" && text[index + 1] === "\n") index += 1;
        row.push(cell); rows.push(row); row = []; cell = "";
      } else cell += char;
    }
    if (cell || row.length) { row.push(cell); rows.push(row); }
    return rows;
  }

  function renderCsvPreview(text, container) {
    const allRows = parseCsv(text);
    const rows = allRows.slice(0, 500);
    const table = document.createElement("table");
    table.className = "preview-text-table";
    rows.forEach((row, index) => {
      const tr = document.createElement("tr");
      row.forEach((value) => {
        const cell = document.createElement(index === 0 ? "th" : "td");
        cell.textContent = value;
        tr.append(cell);
      });
      table.append(tr);
    });
    container.replaceChildren(table);
    if (allRows.length > 500) {
      const note = document.createElement("p");
      note.className = "preview-note";
      note.textContent = "Showing the first 500 rows. Download the file to see the complete content.";
      container.prepend(note);
    }
  }

  async function openFilePreview(file) {
    if (!state.currentZip) { toast("The package preview is no longer available; retrieve the ZIP again."); return; }
    if (state.previewObjectUrl) URL.revokeObjectURL(state.previewObjectUrl);
    state.previewObjectUrl = null;
    const modal = $("#previewModal");
    const container = $("#previewBody");
    $("#previewTitle").textContent = safeText(file.name);
    $("#previewSubtitle").textContent = `${artifactCategory(file.name)} · ${prettyBytes(file.size)}`;
    container.replaceChildren(Object.assign(document.createElement("p"), { className: "preview-loading", textContent: "Opening file…" }));
    modal.classList.remove("hidden");
    document.body.classList.add("preview-open");
    $("#previewDownload").onclick = () => downloadPackageFile(file);
    try {
      if (file.size > 100 * 1024 * 1024) throw new Error("This file is too large to preview in the browser. Use Download file instead.");
      const blob = await readZipEntry(state.currentZip, file);
      const ext = fileExtension(file.name);
      if (ext === "docx") {
        await renderDocxPreview(blob, container);
      } else if (ext === "pdf") {
        const url = URL.createObjectURL(blob.slice(0, blob.size, "application/pdf"));
        state.previewObjectUrl = url;
        const frame = document.createElement("iframe");
        frame.className = "preview-pdf-frame";
        frame.title = `PDF preview: ${safeText(file.name)}`;
        frame.src = url;
        container.replaceChildren(frame);
      } else if (["png", "jpg", "jpeg", "webp", "gif", "svg", "tif", "tiff"].includes(ext)) {
        const url = URL.createObjectURL(blob.slice(0, blob.size, mimeTypeFor(file.name)));
        state.previewObjectUrl = url;
        const image = document.createElement("img");
        image.className = "preview-image";
        image.alt = safeText(file.name);
        image.src = url;
        container.replaceChildren(image);
      } else {
        const text = await blob.text();
        if (ext === "json") {
          const pre = document.createElement("pre");
          pre.className = "preview-code";
          try { pre.textContent = JSON.stringify(JSON.parse(text), null, 2); }
          catch { pre.textContent = text; }
          container.replaceChildren(pre);
        } else if (ext === "csv") {
          renderCsvPreview(text, container);
        } else {
          const pre = document.createElement("pre");
          pre.className = "preview-code";
          pre.textContent = text;
          container.replaceChildren(pre);
        }
      }
    } catch (error) {
      showPreviewError(error.message || "This file cannot be previewed in the browser.");
    }
  }

  async function downloadPackageFile(file) {
    if (!state.currentZip) { toast("The package is no longer available; retrieve the ZIP again."); return; }
    try {
      const blob = await readZipEntry(state.currentZip, file);
      downloadBlob(blob, file.name);
    } catch (error) {
      toast(error.message || "Could not extract this file from the ZIP.");
    }
  }

  function openOriginalPdfPreview() {
    const record = state.currentPackage;
    if (!record?.sourcePdf) { toast("The original PDF preview is no longer available in this page session."); return; }
    if (state.previewObjectUrl) URL.revokeObjectURL(state.previewObjectUrl);
    const details = record.sourcePageCount ? `${record.sourcePageCount} pages` : "Page count unavailable";
    const title = safeText(record.filename || record.sourcePdf.name);
    $("#previewTitle").textContent = title;
    $("#previewSubtitle").textContent = `Original uploaded PDF · ${details} · ${prettyBytes(record.sourcePdf.size)}`;
    const frame = document.createElement("iframe");
    frame.className = "preview-pdf-frame";
    frame.title = `Original PDF preview: ${title}`;
    state.previewObjectUrl = URL.createObjectURL(record.sourcePdf);
    frame.src = state.previewObjectUrl;
    $("#previewBody").replaceChildren(frame);
    $("#previewDownload").onclick = () => downloadBlob(record.sourcePdf, record.filename || record.sourcePdf.name);
    $("#previewModal").classList.remove("hidden");
    document.body.classList.add("preview-open");
  }

  function closePreview() {
    $("#previewModal").classList.add("hidden");
    document.body.classList.remove("preview-open");
    $("#previewBody").replaceChildren();
    if (state.previewObjectUrl) URL.revokeObjectURL(state.previewObjectUrl);
    state.previewObjectUrl = null;
  }

  async function submit() {
    if (!state.file || !state.configConfigured || state.pageCountPending) return;
    state.webhookSource?.close();
    state.webhookSource = null;
    const pageRange = selectedPageRange();
    const pageRangeError = $("#pageRangeError");
    if (pageRange.error) {
      pageRangeError.textContent = pageRange.error;
      pageRangeError.classList.remove("hidden");
      return;
    }
    pageRangeError.classList.add("hidden");
    pageRangeError.textContent = "";
    $("#submitError").classList.add("hidden");
    $("#submissionSuccess").classList.add("hidden");
    $("#resultPollingError").classList.add("hidden");
    $("#progressCard").classList.remove("hidden");
    $("#submitButton").disabled = true;
    const body = new FormData();
    body.append("file", state.file, state.file.name);
    for (const [name, value] of Object.entries(extractionOptions())) body.append(name, String(value));
    if (pageRange.start !== null && pageRange.end !== null) {
      body.append("start_page", String(pageRange.start));
      body.append("end_page", String(pageRange.end));
    }
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
        statusText: String(data.status),
        sourcePdf: state.file,
        sourcePageCount: Number.isInteger(data.page_count) ? data.page_count : state.pageCount,
        pageRange: pageRange.start === null ? null : { start: pageRange.start, end: pageRange.end },
        size: state.file.size, callbackConfigured: Boolean(data.callback_configured),
        extractionOptions: extractionOptions(), auditTrail: [], webhookEnabled: data.webhook_enabled === true,
      };
      state.currentSubmission = record;
      $("#submissionStatus").textContent = safeText(record.statusText);
      $("#submissionRequestId").textContent = requestId;
      $("#submissionSuccess").classList.remove("hidden");
      toast("PDFLens accepted the request.");
      resetFile();
      $("#retrieveSubmitted").disabled = false;
      $("#retrieveSubmitted").textContent = record.webhookEnabled ? "Check result now" : "Retrieve result";
      recordRequestAudit(record, "Submitted", "PDFLens accepted the request.");
      recordRequestAudit(record, record.statusText, "Status returned by PDFLens.");
      if (record.webhookEnabled) {
        recordRequestAudit(record, "Waiting for webhook", "The UI will request the ZIP once PDFLens reports completion.");
        listenForPdfLensWebhook(record);
      }
    } catch (error) {
      const message = error.message || "The request could not be completed.";
      $("#submitErrorMessage").textContent = message;
      const failedRequestId = error.requestId || requestId;
      $("#submitErrorId").textContent = failedRequestId ? `Request ID: ${failedRequestId}` : "";
      $("#submitError").classList.remove("hidden");
    } finally {
      $("#progressCard").classList.add("hidden");
      $("#submitButton").disabled = !state.file || !state.configConfigured || state.pageCountPending;
    }
  }

  async function retrieveResult(record, trigger = null, options = {}) {
    if (!record?.requestId || state.resultPolling) return;
    // Use one-shot retrieval only when this UI receives the callback itself.
    const singleAttempt = options.singleAttempt ?? Boolean(record.webhookEnabled);
    state.resultPolling = true;
    const originalLabel = trigger?.textContent;
    if (trigger) { trigger.disabled = true; trigger.textContent = "Requesting…"; }
    if (record === state.currentSubmission) $("#retrieveSubmitted").disabled = true;
    const pollingCard = $("#resultPollingCard");
    const pollingText = $("#resultPollingText");
    const pollingFootprint = $("#resultPollingFootprint");
    const pollError = $("#resultPollingError");
    const started = Date.now();
    let attempt = 0;
    let receivedZip = false;
    recordRequestAudit(record, "Retrieval started", options.triggeredByWebhook ? "Requesting the ZIP once after the completion callback." : "Manual result check started.");
    pollError.classList.add("hidden");
    pollingCard.classList.remove("hidden");
    pollingText.textContent = singleAttempt
      ? "Checking PDFLens once for the result ZIP."
      : `Checking PDFLens every ${state.resultPollIntervalSeconds} seconds for up to ${Math.ceil(state.resultPollMaxWaitSeconds / 60)} minutes.`;
    pollingFootprint.textContent = `Request ID: ${record.requestId}`;
    const elapsedTimer = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - started) / 1000);
      pollingFootprint.textContent = `Attempt ${attempt || 1} · elapsed ${elapsed}s of ${state.resultPollMaxWaitSeconds}s · request ${record.requestId}`;
    }, 1000);
    toast("Checking whether PDFLens has finished processing…");
    try {
      while (singleAttempt ? attempt === 0 : (Date.now() - started) / 1000 < state.resultPollMaxWaitSeconds) {
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
          if (record === state.currentSubmission && !singleAttempt) $("#submissionStatus").textContent = upstreamStatus;
          recordRequestAudit(record, upstreamStatus, "PDFLens has not returned the result ZIP yet.", attempt);
          pollingText.textContent = `PDFLens status: ${upstreamStatus}. Checking again in ${state.resultPollIntervalSeconds} seconds.`;
          if (singleAttempt) {
            const pendingError = new Error(`PDFLens still reports ${upstreamStatus}. Wait for its next webhook update or select Check result now to try once again.`);
            pendingError.resultPending = true;
            throw pendingError;
          }
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
        state.webhookSource?.close();
        state.webhookSource = null;
        if (record === state.currentSubmission) $("#submissionStatus").textContent = "Completed";
        recordRequestAudit(record, "Completed", `Result ZIP retrieved after ${attempt} check${attempt === 1 ? "" : "s"}.`, attempt);
        resetPageComparison(packageRecord);
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
      if (record === state.currentSubmission && !error.resultPending) $("#submissionStatus").textContent = "Retrieval issue";
      recordRequestAudit(record, error.resultPending ? "Result not ready" : "Retrieval issue", message, attempt || null);
      $("#resultPollingErrorText").textContent = message;
      $("#resultPollingErrorId").textContent = `Request ID: ${record.requestId}`;
      pollError.classList.remove("hidden");
      toast(message);
    } finally {
      window.clearInterval(elapsedTimer);
      pollingCard.classList.add("hidden");
      state.resultPolling = false;
      if (trigger) { trigger.disabled = false; trigger.textContent = originalLabel; }
      if (record === state.currentSubmission && !pollError.classList.contains("hidden")) {
        $("#retrieveSubmitted").disabled = false;
        $("#retrieveSubmitted").textContent = record.webhookEnabled ? "Check result now" : "Retry result retrieval";
      } else if (record === state.currentSubmission) {
        $("#retrieveSubmitted").disabled = false;
        $("#retrieveSubmitted").textContent = record.webhookEnabled ? "Check result now" : "Retrieve result";
      }
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
    $("#packageRequest").textContent = record.requestId ? `Request ID: ${record.requestId}` : "Request ID not returned";
    renderRequestAudit(record);
    if (record.sourcePageCount) {
      $("#packageRequest").textContent += ` · Source PDF: ${record.sourcePageCount} pages`;
    }
    $("#sourcePdfName").textContent = safeText(record.filename || record.sourcePdf?.name || "Original uploaded PDF");
    const sourceDetails = [
      "Original uploaded PDF",
      record.sourcePageCount ? `${record.sourcePageCount} pages` : "Page count unavailable",
      record.pageRange ? `Processed pages ${record.pageRange.start}–${record.pageRange.end}` : "Full document processed",
      record.sourcePdf ? prettyBytes(record.sourcePdf.size) : "Original file unavailable",
    ];
    $("#sourcePdfDetails").textContent = sourceDetails.join(" · ");
    $("#sourcePdfCard").classList.toggle("hidden", !record.sourcePdf);
    $("#packageSize").textContent = prettyBytes(record.packageBytes);
    $("#packageTime").textContent = `Retrieved ${dateLabel(record.retrievedAt || record.submittedAt)}`;
    const categories = record.files.map((file) => artifactCategory(file.name));
    $("#packageFileCount").textContent = String(record.files.length);
    $("#packageDocuments").textContent = String(categories.filter((category) => category === "Document").length);
    $("#packageMetadata").textContent = String(categories.filter((category) => category === "Metadata").length);
    $("#packageAssets").textContent = String(categories.filter((category) => ["Image asset", "Table snapshot"].includes(category)).length);
    const tbody = $("#packageRows");
    tbody.replaceChildren();
    const imageFiles = record.files.filter((file) => artifactCategory(file.name) === "Image asset");
    const tableFiles = record.files.filter((file) => artifactCategory(file.name) === "Table snapshot");
    const insertedGroups = new Set();
    for (const file of record.files) {
      const category = artifactCategory(file.name);
      const group = category === "Image asset" ? "images" : category === "Table snapshot" ? "tables" : "";
      if (group) {
        if (!insertedGroups.has(group)) {
          const groupFiles = group === "images" ? imageFiles : tableFiles;
          tbody.append(createAssetFolderRow(group === "images" ? "Images" : "Tables", group, groupFiles));
          groupFiles.forEach((groupFile) => tbody.append(createPackageFileRow(groupFile, group)));
          insertedGroups.add(group);
        }
        continue;
      }
      tbody.append(createPackageFileRow(file));
    }
    $("#downloadAgain").onclick = () => {
      if (state.currentZip) downloadBlob(state.currentZip, record.packageName);
      else retrieveResult(record, $("#downloadAgain"));
    };
    $("#previewSourcePdf").onclick = openOriginalPdfPreview;
    $("#downloadSourcePdf").onclick = () => {
      if (record.sourcePdf) downloadBlob(record.sourcePdf, record.filename || record.sourcePdf.name);
    };
  }

  function resetPageComparison(record) {
    state.compareRenderId += 1;
    state.comparePageRenderId += 1;
    for (const url of state.comparePdfUrls) URL.revokeObjectURL(url);
    state.comparePdfUrls.clear();
    state.comparePdfUrl = null;
    state.compareMetadata = null;
    state.compareMetadataPromise = null;
    state.compareDocxPages = null;
    state.compareDocxParagraphs = null;
    state.compareDocxUsesBookmarks = false;
    state.compareDocxPromise = null;
    state.comparePage = record.pageRange?.start || 1;
    clearComparisonAssetUrls();
  }

  function clearComparisonAssetUrls() {
    for (const url of state.compareAssetUrls) URL.revokeObjectURL(url);
    state.compareAssetUrls = [];
  }

  function sourcePageBounds(record) {
    const metadataPages = Array.isArray(state.compareMetadata) ? state.compareMetadata : state.compareMetadata?.pages;
    const totalPages = Number(record.sourcePageCount) || Number(metadataPages?.length) || 1;
    return {
      start: record.pageRange?.start || 1,
      end: record.pageRange?.end || totalPages,
      total: totalPages,
    };
  }

  async function loadComparisonMetadata() {
    if (state.compareMetadataPromise) return state.compareMetadataPromise;
    state.compareMetadataPromise = (async () => {
      const zip = state.currentZip;
      const packageRecord = state.currentPackage;
      if (!zip || !packageRecord) return null;
      const candidates = (packageRecord.files || []).filter((file) => fileExtension(file.name) === "json")
        .sort((left, right) => {
          const rank = (file) => /^meta\.json$/i.test(file.name.split("/").pop()) ? 0 : /(?:^|[_-])metadata\.json$/i.test(file.name.split("/").pop()) ? 1 : /metadata/i.test(file.name) ? 2 : 3;
          return rank(left) - rank(right);
        });
      for (const entry of candidates) {
        try {
          const parsed = JSON.parse(await (await readZipEntry(zip, entry)).text());
          if (zip !== state.currentZip || packageRecord !== state.currentPackage) return null;
          if (Array.isArray(parsed) || (parsed && Array.isArray(parsed.pages))) { state.compareMetadata = parsed; break; }
        } catch { /* try another JSON file in the package */ }
      }
      return state.compareMetadata;
    })();
    return state.compareMetadataPromise;
  }

  async function loadComparisonDocxPages() {
    if (state.compareDocxPages) return state.compareDocxPages;
    if (state.compareDocxPromise) return state.compareDocxPromise;
    state.compareDocxPromise = (async () => {
      const zip = state.currentZip;
      const packageRecord = state.currentPackage;
      const entry = packageRecord?.files?.find((file) => fileExtension(file.name) === "docx");
      if (!entry || !zip) return null;
      const archive = await readZipEntry(zip, entry);
      const contents = await readZipDirectory(archive);
      const documentEntry = contents.find((file) => file.name === "word/document.xml");
      if (!documentEntry) return null;
      const xml = new DOMParser().parseFromString(await (await readZipEntry(archive, documentEntry)).text(), "application/xml");
      if (xml.querySelector("parsererror")) return null;
      const ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
      const body = xml.getElementsByTagNameNS(ns, "body")[0];
      if (!body) return null;
      const pages = new Map();
      const allParagraphs = [];
      let currentPage = 1;
      let hasBookmarks = false;
      const appendText = (page, text, style = "") => {
        if (!text.trim()) return;
        const paragraph = { text, style };
        allParagraphs.push(paragraph);
        if (!pages.has(page)) pages.set(page, []);
        pages.get(page).push(paragraph);
      };
      for (const child of body.children) {
        if (child.localName === "p") {
          for (const bookmark of child.getElementsByTagNameNS(ns, "bookmarkStart")) {
            const name = bookmark.getAttributeNS(ns, "name") || bookmark.getAttribute("w:name") || "";
            const match = name.match(/^pdflens_page_(\d+)$/i);
            if (match) {
              currentPage = Number(match[1]); hasBookmarks = true;
              if (!pages.has(currentPage)) pages.set(currentPage, []);
            }
          }
          const text = [...child.getElementsByTagNameNS(ns, "t")].map((node) => node.textContent || "").join("");
          const styleNode = child.getElementsByTagNameNS(ns, "pStyle")[0];
          const styleName = styleNode?.getAttributeNS(ns, "val") || styleNode?.getAttribute("w:val") || "";
          const heading = styleName.match(/heading\s*(\d)|heading(\d)/i);
          appendText(currentPage, text, heading ? `Heading ${heading[1] || heading[2]}` : "");
          const breakAfter = [...child.getElementsByTagNameNS(ns, "br")].some((node) => (node.getAttributeNS(ns, "type") || node.getAttribute("w:type")) === "page")
            || child.getElementsByTagNameNS(ns, "lastRenderedPageBreak").length > 0
            || child.getElementsByTagNameNS(ns, "sectPr").length > 0;
          if (!hasBookmarks && breakAfter) currentPage += 1;
        } else if (child.localName === "tbl") {
          const text = [...child.getElementsByTagNameNS(ns, "t")].map((node) => node.textContent || "").join(" | ");
          appendText(currentPage, text, "");
        }
      }
      if (zip !== state.currentZip || packageRecord !== state.currentPackage) return null;
      state.compareDocxPages = pages;
      state.compareDocxParagraphs = allParagraphs;
      state.compareDocxUsesBookmarks = hasBookmarks;
      return pages;
    })();
    const loadingPromise = state.compareDocxPromise;
    try {
      return await loadingPromise;
    } catch (error) {
      if (state.compareDocxPromise === loadingPromise) state.compareDocxPromise = null;
      throw error;
    }
  }

  function metadataPageForSourcePage(metadata, sourcePage, record) {
    const pages = Array.isArray(metadata) ? metadata : metadata?.pages;
    if (!Array.isArray(pages)) return null;
    if (record.pageRange) {
      const hasSourcePageNumbers = pages.some((page) => Number(page.page_number) === record.pageRange.start)
        && pages.some((page) => Number(page.page_number) === record.pageRange.end);
      if (hasSourcePageNumbers) {
        const exact = pages.find((page) => Number(page.page_number) === sourcePage);
        if (exact) return exact;
      }
      const localPage = sourcePage - record.pageRange.start + 1;
      return pages.find((page) => Number(page.page_number) === localPage) || pages[localPage - 1] || null;
    }
    const exact = pages.find((page) => Number(page.page_number) === sourcePage);
    if (exact) return exact;
    return pages[sourcePage - 1] || null;
  }

  function appendCompareText(parent, tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text;
    parent.append(node);
    return node;
  }

  function safeMetadataHref(value) {
    try {
      const url = new URL(String(value || "").trim());
      return ["http:", "https:", "mailto:"].includes(url.protocol) ? url.href : "";
    } catch {
      return "";
    }
  }

  function renderFriendlyMetadata(page, metadata, sourcePage, container) {
    const article = document.createElement("article"); article.className = "compare-metadata-page";
    appendCompareText(article, "div", "compare-metadata-eyebrow", "PAGE EXTRACTION");
    appendCompareText(article, "h3", "compare-metadata-title", `Page ${sourcePage}`);
    const facts = document.createElement("div"); facts.className = "compare-page-facts";
    const imageNames = [...new Set(["body", "header", "footer"].flatMap((key) => Array.isArray(page.image?.[key]) ? page.image[key] : []))];
    const factValues = [
      ["Metadata page", page.page_number ?? sourcePage],
      ["Page type", page.page_type || "Not provided"],
      ["Page size", Number.isFinite(Number(page.width_pt)) && Number.isFinite(Number(page.height_pt)) ? `${Number(page.width_pt).toFixed(1)} × ${Number(page.height_pt).toFixed(1)} pt` : "Not provided"],
      ["Images", imageNames.length], ["Tables", Array.isArray(page.table) ? page.table.length : 0],
    ];
    for (const [label, value] of factValues) {
      const item = document.createElement("div"); item.className = "compare-page-fact";
      appendCompareText(item, "small", "", label); appendCompareText(item, "b", "", String(value)); facts.append(item);
    }
    article.append(facts);

    appendCompareText(article, "h4", "compare-section-title", "Body text");
    const body = String(page.full_text || page.body_text || "").trim();
    if (body) {
      const bodyBox = document.createElement("div"); bodyBox.className = "compare-body-text";
      body.split(/\n+/).filter((line) => line.trim()).forEach((line) => appendCompareText(bodyBox, "p", "", line.trim()));
      article.append(bodyBox);
    } else appendCompareText(article, "p", "compare-no-content", "No page body text was extracted.");

    appendCompareText(article, "h4", "compare-section-title", "Headers and footers");
    const furniture = document.createElement("div"); furniture.className = "compare-furniture-grid";
    for (const [label, value] of [["Header", page.header], ["Footer", page.footer]]) {
      const item = document.createElement("div"); item.className = "compare-furniture-item";
      appendCompareText(item, "small", "", label);
      appendCompareText(item, "p", "", Array.isArray(value) ? value.join("\n") : String(value || "—"));
      furniture.append(item);
    }
    article.append(furniture);

    appendCompareText(article, "h4", "compare-section-title", "Images on this page");
    if (!imageNames.length) appendCompareText(article, "p", "compare-no-content", "No image files are listed for this page.");
    else for (const imageName of imageNames) appendCompareText(article, "div", "compare-inline-asset", imageName);

    appendCompareText(article, "h4", "compare-section-title", "Tables on this page");
    const tables = Array.isArray(page.table) ? page.table : [];
    if (!tables.length) appendCompareText(article, "p", "compare-no-content", "No tables are listed for this page.");
    for (const [index, table] of tables.entries()) {
      const card = document.createElement("article"); card.className = "compare-element-card";
      appendCompareText(card, "div", "compare-element-type", `Table ${index + 1}`);
      appendCompareText(card, "pre", "compare-structured-value", typeof table === "string" ? table : JSON.stringify(table, null, 2));
      article.append(card);
    }

    appendCompareText(article, "h4", "compare-section-title", "Footnotes");
    const footnotes = Array.isArray(page.footnote) ? page.footnote : [];
    if (!footnotes.length) appendCompareText(article, "p", "compare-no-content", "No footnotes are listed for this page.");
    for (const [index, footnote] of footnotes.entries()) {
      const text = typeof footnote === "string" ? footnote : footnote?.text || JSON.stringify(footnote);
      const card = document.createElement("article"); card.className = "compare-element-card compare-footnote-card";
      appendCompareText(card, "span", "compare-element-type", `Footnote ${index + 1}`);
      appendCompareText(card, "p", "compare-element-text", text);
      article.append(card);
    }

    appendCompareText(article, "h4", "compare-section-title", "Hyperlinks");
    const hyperlinks = Array.isArray(page.hyperlink) ? page.hyperlink : [];
    if (!hyperlinks.length) appendCompareText(article, "p", "compare-no-content", "No hyperlinks are listed for this page.");
    for (const linkData of hyperlinks) {
      const row = document.createElement("div"); row.className = "compare-hyperlink";
      const item = typeof linkData === "string" ? { uri: linkData } : (linkData || {});
      const uri = String(item.uri || item.target_uri || "");
      const description = [item.text, item.page_number ? `Page ${item.page_number}` : "", Number.isInteger(item.hyperlink_index) ? `Link ${item.hyperlink_index}` : ""].filter(Boolean).join(" · ");
      appendCompareText(row, "p", "", description || uri || "Hyperlink");
      const href = safeMetadataHref(uri);
      if (href) {
        const link = document.createElement("a"); link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = uri; row.append(link);
      }
      article.append(row);
    }

    appendCompareText(article, "h4", "compare-section-title", "Structured elements");
    const elements = Array.isArray(page.elements) ? page.elements : [];
    if (!elements.length) appendCompareText(article, "p", "compare-no-content", "No individual elements were recorded for this page.");
    for (const element of elements) {
      const card = document.createElement("article"); card.className = "compare-element-card";
      const top = document.createElement("div"); top.className = "compare-element-top";
      appendCompareText(top, "span", "compare-element-type", String(element.type || "element").replaceAll("_", " "));
      if (element.reading_order !== undefined && element.reading_order !== null) appendCompareText(top, "small", "", `Reading order ${element.reading_order}`);
      card.append(top);
      if (element.text) appendCompareText(card, "p", "compare-element-text", element.text);
      if (element.target_uri) {
        const href = safeMetadataHref(element.target_uri);
        if (href) {
          const link = document.createElement("a"); link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = String(element.target_uri); card.append(link);
        }
      }
      if (element.artifact_path) appendCompareText(card, "small", "compare-element-path", `Snapshot: ${element.artifact_path}`);
      article.append(card);
    }

    const raw = document.createElement("details"); raw.className = "compare-raw-details";
    const summary = document.createElement("summary"); summary.textContent = "View raw page JSON"; raw.append(summary);
    const pre = document.createElement("pre"); pre.className = "preview-code compare-metadata-raw"; pre.textContent = JSON.stringify(page, null, 2); raw.append(pre);
    article.append(raw);
    container.replaceChildren(article);
  }

  function comparisonTokens(text) {
    return String(text || "").toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
  }

  function fitDocxContentToPane() {
    const container = $("#compareOutputBody");
    const sheet = container?.querySelector(".compare-docx-page");
    if (!sheet || !container.classList.contains("compare-docx-fit")) return;
    sheet.style.transform = "none";
    const availableWidth = Math.max(1, container.clientWidth - 16);
    const availableHeight = Math.max(1, container.clientHeight - 16);
    sheet.style.width = `${availableWidth}px`;
    sheet.style.maxWidth = "none";
    sheet.style.minHeight = "0";
    const contentHeight = Math.max(sheet.scrollHeight, 1);
    const scale = Math.min(1, availableHeight / contentHeight);
    const scaledWidth = availableWidth * scale;
    sheet.style.left = `${Math.max(8, (container.clientWidth - scaledWidth) / 2)}px`;
    sheet.style.top = "8px";
    sheet.style.transformOrigin = "top left";
    sheet.style.transform = `scale(${scale})`;
  }

  function mapDocxParagraphsToMetadataPages(paragraphs, metadata, record) {
    const bounds = sourcePageBounds(record);
    const pageRecords = [];
    for (let pageNumber = bounds.start; pageNumber <= bounds.end; pageNumber += 1) {
      const metadataPage = metadataPageForSourcePage(metadata, pageNumber, record);
      pageRecords.push({ pageNumber, tokens: new Set(comparisonTokens(metadataPage?.full_text || metadataPage?.body_text || "")) });
    }
    if (!pageRecords.some((page) => page.tokens.size)) return null;
    const mapped = new Map(pageRecords.map((page) => [page.pageNumber, []]));
    let lastIndex = 0;
    paragraphs.forEach((paragraph, paragraphIndex) => {
      const words = comparisonTokens(paragraph.text);
      let selectedIndex = Math.min(lastIndex, pageRecords.length - 1);
      let bestScore = 0;
      for (let pageIndex = lastIndex; pageIndex < pageRecords.length; pageIndex += 1) {
        let score = 0;
        for (const word of words) if (pageRecords[pageIndex].tokens.has(word)) score += 1;
        if (score > bestScore) { bestScore = score; selectedIndex = pageIndex; }
      }
      if (!bestScore) selectedIndex = Math.min(lastIndex, pageRecords.length - 1);
      else lastIndex = selectedIndex;
      mapped.get(pageRecords[selectedIndex].pageNumber).push(paragraph);
    });
    return mapped;
  }

  async function renderComparisonOutput() {
    const renderId = ++state.compareRenderId;
    const isCurrent = () => renderId === state.compareRenderId;
    clearComparisonAssetUrls();
    const container = $("#compareOutputBody");
    const view = $("#compareOutputView").value;
    const record = state.currentPackage;
    const pageNumber = state.comparePage;
    container.classList.toggle("compare-docx-fit", view === "docx");
    $("#compareOutputPageLabel").textContent = `Showing output for source page ${pageNumber}`;
    container.replaceChildren();
    const loading = document.createElement("p"); loading.className = "preview-loading"; loading.textContent = "Opening page content…"; container.append(loading);

    if (view === "metadata") {
      const metadata = await loadComparisonMetadata();
      if (!isCurrent()) return;
      const page = metadataPageForSourcePage(metadata, pageNumber, record);
      if (!page) { showCompareMessage("No matching metadata page was found in this ZIP."); return; }
      renderFriendlyMetadata(page, metadata, pageNumber, container);
      return;
    }

    if (view === "images" || view === "tables") {
      const metadata = await loadComparisonMetadata();
      if (!isCurrent()) return;
      const page = metadataPageForSourcePage(metadata, pageNumber, record);
      const kind = view === "images" ? "image" : "table";
      const pageTokens = view === "images"
        ? [...new Set(["body", "header", "footer"].flatMap((key) => Array.isArray(page?.image?.[key]) ? page.image[key] : []))]
        : (Array.isArray(page?.table) ? page.table : []);
      const assetPaths = [
        ...pageTokens.filter((item) => typeof item === "string"),
        ...pageTokens.filter((item) => item && typeof item === "object").flatMap((item) => [item.artifact_path, item.path, item.file, item.filename, item.snapshot_path, item.snapshot, item.asset_path, item.image_path, item.snapshot_file, item.table_path].filter(Boolean)),
        ...(page?.elements || []).filter((element) => String(element.type || "").toLowerCase().includes(kind)).map((element) => element.artifact_path).filter(Boolean),
      ].map((path) => String(path).replaceAll("\\", "/").toLowerCase());
      const imageExtensions = ["png", "jpg", "jpeg", "webp", "gif", "tif", "tiff"];
      const isAssetType = (file) => {
        const lower = file.name.toLowerCase();
        const normalizedName = lower.replaceAll("\\", "/");
        const explicitlyReferenced = assetPaths.some((path) => normalizedName === path || normalizedName.endsWith(`/${path}`) || normalizedName.endsWith(`/${path.split("/").pop()}`));
        return imageExtensions.includes(fileExtension(file.name))
          && (explicitlyReferenced || (kind === "image" ? !/table/i.test(lower) : /table/i.test(lower)));
      };
      let assets = (record.files || []).filter((file) => isAssetType(file) && assetPaths.some((path) => {
        const name = file.name.replaceAll("\\", "/").toLowerCase();
        return name === path || name.endsWith(`/${path}`) || name.endsWith(`/${path.split("/").pop()}`);
      }));
      if (!assets.length) {
        const pageToken = new RegExp(`(?:page|p)[-_]?0*${pageNumber}(?:[-_]|\\.)`, "i");
        assets = (record.files || []).filter((file) => isAssetType(file) && pageToken.test(file.name));
      }
      if (!assets.length) { showCompareMessage(`No ${kind} files are linked to source page ${pageNumber} in the result package.`); return; }
      const assetCards = document.createDocumentFragment();
      for (const asset of assets) {
        const card = document.createElement("article"); card.className = "compare-asset-card";
        const title = document.createElement("b"); title.textContent = asset.name;
        card.append(title);
        if (["png", "jpg", "jpeg", "webp", "gif"].includes(fileExtension(asset.name))) {
          try {
            const blob = await readZipEntry(state.currentZip, asset);
            if (!isCurrent()) return;
            const url = URL.createObjectURL(blob); state.compareAssetUrls.push(url);
            const image = document.createElement("img"); image.src = url; image.alt = asset.name; card.append(image);
          } catch (error) {
            const note = document.createElement("small"); note.textContent = error.message || "Could not open this snapshot."; card.append(note);
          }
        }
        const download = document.createElement("button"); download.className = "button button-secondary"; download.textContent = "Download snapshot";
        download.addEventListener("click", () => downloadPackageFile(asset)); card.append(download); assetCards.append(card);
      }
      if (isCurrent()) container.replaceChildren(assetCards);
      return;
    }

    try {
      const pages = await loadComparisonDocxPages();
      if (!isCurrent()) return;
      const docxPageNumber = state.compareDocxUsesBookmarks || !record.pageRange
        ? pageNumber
        : pageNumber - record.pageRange.start + 1;
      let content = pages?.get(docxPageNumber);
      if (!content?.length && !pages?.has(docxPageNumber)) {
        const metadata = await loadComparisonMetadata();
        if (!isCurrent()) return;
        const mappedPages = mapDocxParagraphsToMetadataPages(state.compareDocxParagraphs || [], metadata, record);
        content = mappedPages?.get(pageNumber);
      }
      if (!content) { showCompareMessage("This DOCX does not include a page marker for this source page. Try the Metadata or Images & tables view."); return; }
      if (!content.length) { showCompareMessage("No readable DOCX text was mapped to this source page. Try the Metadata or Images & tables view."); return; }
      const article = document.createElement("article"); article.className = "docx-preview compare-docx-page";
      for (const paragraph of content) {
        const node = document.createElement(paragraph.style ? `h${paragraph.style.match(/\d/)?.[0] || 2}` : "p");
        node.textContent = paragraph.text; article.append(node);
      }
      container.replaceChildren(article);
      requestAnimationFrame(fitDocxContentToPane);
    } catch (error) {
      if (isCurrent()) showCompareMessage(error.message || "Could not open the DOCX page content.");
    }
  }

  function showCompareMessage(message) {
    const note = document.createElement("p"); note.className = "compare-empty-note"; note.textContent = message;
    $("#compareOutputBody").replaceChildren(note);
  }

  async function renderPageComparison() {
    const pageRenderId = ++state.comparePageRenderId;
    const record = state.currentPackage;
    const requestedPage = state.comparePage;
    const ready = Boolean(record?.sourcePdf && state.currentZip);
    $("#validationEmpty").classList.toggle("hidden", ready);
    $("#pageCompare").classList.toggle("hidden", !ready);
    if (!ready) return;
    await loadComparisonMetadata();
    if (record !== state.currentPackage || pageRenderId !== state.comparePageRenderId || requestedPage !== state.comparePage) return;
    const bounds = sourcePageBounds(record);
    state.comparePage = Math.max(bounds.start, Math.min(bounds.end, Number(state.comparePage) || bounds.start));
    $("#compareDocumentName").textContent = record.filename || record.sourcePdf.name;
    $("#comparePageCount").textContent = `${bounds.total} pages in the source PDF${record.pageRange ? ` · processed pages ${bounds.start}–${bounds.end}` : ""}`;
    $("#comparePdfName").textContent = record.filename || record.sourcePdf.name;
    $("#comparePageNumber").min = String(bounds.start);
    $("#comparePageNumber").max = String(bounds.end);
    $("#comparePageNumber").value = String(state.comparePage);
    $("#comparePageTotal").textContent = `of ${bounds.end}`;
    $("#previousComparePage").disabled = state.comparePage <= bounds.start;
    $("#nextComparePage").disabled = state.comparePage >= bounds.end;
    const frame = $("#comparePdfFrame");
    const pdfUrl = URL.createObjectURL(record.sourcePdf);
    state.comparePdfUrl = pdfUrl;
    state.comparePdfUrls.add(pdfUrl);
    frame.onload = () => {
      if (state.comparePdfUrl !== pdfUrl) return;
      for (const oldUrl of state.comparePdfUrls) {
        if (oldUrl !== pdfUrl) { URL.revokeObjectURL(oldUrl); state.comparePdfUrls.delete(oldUrl); }
      }
    };
    frame.src = `${pdfUrl}#page=${state.comparePage}&toolbar=0&navpanes=0`;
    renderComparisonOutput();
  }

  function resetComparisonPage() {
    const bounds = sourcePageBounds(state.currentPackage);
    const requested = Number($("#comparePageNumber").value);
    if (!Number.isInteger(requested) || requested < bounds.start || requested > bounds.end) {
      $("#comparePageNumber").value = String(state.comparePage);
      toast(`Choose a page from ${bounds.start} to ${bounds.end}.`);
      return;
    }
    state.comparePage = requested;
    renderPageComparison();
  }

  function stepComparePage(offset) {
    const bounds = sourcePageBounds(state.currentPackage);
    state.comparePage = Math.max(bounds.start, Math.min(bounds.end, state.comparePage + offset));
    renderPageComparison();
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
    $("#startPage").addEventListener("input", handlePageRangeInput);
    $("#endPage").addEventListener("input", handlePageRangeInput);
    $("#removeFile").addEventListener("click", resetFile);
    $("#submitButton").addEventListener("click", submit);
    $("#previousComparePage").addEventListener("click", () => stepComparePage(-1));
    $("#nextComparePage").addEventListener("click", () => stepComparePage(1));
    $("#comparePageNumber").addEventListener("change", resetComparisonPage);
    $("#comparePageNumber").addEventListener("keydown", (event) => { if (event.key === "Enter") resetComparisonPage(); });
    $("#compareOutputView").addEventListener("change", renderComparisonOutput);
    window.addEventListener("resize", fitDocxContentToPane);
    $("#retrieveSubmitted").addEventListener("click", (event) => retrieveResult(state.currentSubmission, event.currentTarget));
    $("#closePreview").addEventListener("click", closePreview);
    $("#previewModal").addEventListener("click", (event) => {
      if (event.target === $("#previewModal")) closePreview();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !$("#previewModal").classList.contains("hidden")) closePreview();
    });
    $("#dropzone").addEventListener("dragover", (event) => { event.preventDefault(); $("#dropzone").classList.add("dragover"); });
    $("#dropzone").addEventListener("dragleave", () => $("#dropzone").classList.remove("dragover"));
    $("#dropzone").addEventListener("drop", (event) => {
      event.preventDefault();
      $("#dropzone").classList.remove("dragover");
      setFile(event.dataTransfer.files?.[0]);
    });
    checkHealth();
    loadUiSettings();
    navigate("dashboard");
  }

  document.addEventListener("DOMContentLoaded", setup, { once: true });
})();
