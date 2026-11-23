(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const state = {
    file: null, currentZip: null, currentPackage: null, currentSubmission: null,
    health: null, configConfigured: false, previewObjectUrl: null,
    pageCount: null, pageCountAvailable: false, pageCountPending: false, pageInfoRequest: 0,
    resultPollIntervalSeconds: 5, resultPollMaxWaitSeconds: 900,
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
      $("#callbackHelp").textContent = data.callback_configured
        ? "Callback URL: configured by the administrator."
        : "Callback URL: not configured (optional).";
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
      $("#submitButton").disabled = !state.file || !state.configConfigured || state.pageCountPending;
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
      tbody.append(tr);
    });
    $("#downloadAgain").onclick = () => {
      if (state.currentZip) downloadBlob(state.currentZip, record.packageName);
      else retrieveResult(record, $("#downloadAgain"));
    };
    $("#previewSourcePdf").onclick = openOriginalPdfPreview;
    $("#downloadSourcePdf").onclick = () => {
      if (record.sourcePdf) downloadBlob(record.sourcePdf, record.filename || record.sourcePdf.name);
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
    $("#startPage").addEventListener("input", handlePageRangeInput);
    $("#endPage").addEventListener("input", handlePageRangeInput);
    $("#removeFile").addEventListener("click", resetFile);
    $("#submitButton").addEventListener("click", submit);
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
