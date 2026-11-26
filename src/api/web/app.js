const form = document.querySelector("#question-form");
const question = document.querySelector("#question");
const submit = document.querySelector("#submit");
const status = document.querySelector("#status");
const answer = document.querySelector("#answer");
const error = document.querySelector("#error");
const sources = document.querySelector("#sources");
const sourceCount = document.querySelector("#source-count");
const sourcesEmpty = document.querySelector("#sources-empty");

for (const suggestion of document.querySelectorAll(".suggestions button")) {
  suggestion.addEventListener("click", () => {
    question.value = suggestion.textContent.trim();
    question.focus();
  });
}

function appendInline(target, text, citations) {
  for (const part of text.split(/(\[\d+\]|\*\*[^*\n]+\*\*)/g)) {
    const citation = /^\[(\d+)\]$/.exec(part);
    if (citation && citations.has(Number(citation[1]))) {
      const number = Number(citation[1]);
      const link = document.createElement("a");
      link.className = "citation";
      link.href = "#source-" + number;
      link.textContent = part;
      link.addEventListener("click", () => {
        const source = document.getElementById("source-" + number);
        source.open = true;
        source.querySelector("summary").focus({ preventScroll: true });
      });
      target.append(link);
    } else if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      const strong = document.createElement("strong");
      appendInline(strong, part.slice(2, -2), citations);
      target.append(strong);
    } else {
      target.append(document.createTextNode(part));
    }
  }
}

function renderAnswer(text, hits) {
  const citations = new Set(hits.map((hit) => hit.citation));
  let block;
  for (const line of text.trim().split("\n")) {
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    const item = /^\s*(?:([-*])|(\d+)\.)\s+(.+)$/.exec(line);
    if (!line.trim()) {
      block = undefined;
    } else if (heading) {
      const element = document.createElement(heading[1].length <= 2 ? "h3" : "h4");
      appendInline(element, heading[2], citations);
      answer.append(element);
      block = undefined;
    } else if (item) {
      const type = item[1] ? "UL" : "OL";
      if (block?.tagName !== type) {
        block = document.createElement(type);
        if (type === "OL") block.start = Number(item[2]);
        answer.append(block);
      }
      const element = document.createElement("li");
      appendInline(element, item[3], citations);
      block.append(element);
    } else {
      if (block?.tagName !== "P") {
        block = document.createElement("p");
        answer.append(block);
      } else {
        block.append("\n");
      }
      appendInline(block, line, citations);
    }
  }
}

function syncedRelativePath(source) {
  return /^onedrive\/[a-f0-9]{64}\/(.+)$/.exec(source)?.[1];
}

function sourceName(path) {
  const synced = syncedRelativePath(path);
  if (synced) return synced;
  if (/^https?:\/\//i.test(path)) {
    const url = new URL(path);
    return url.hostname + (url.pathname === "/" ? "" : url.pathname);
  }
  return path.split(/[\\/]/).pop() || path;
}

function renderSources(hits) {
  for (const hit of hits) {
    const item = document.createElement("li");
    const details = document.createElement("details");
    details.id = "source-" + hit.citation;
    const summary = document.createElement("summary");
    const title = document.createElement("span");
    title.className = "source-name";
    title.textContent = "[" + hit.citation + "] " + sourceName(hit.source);
    title.title = syncedRelativePath(hit.source) || hit.source;
    const location = document.createElement("span");
    location.className = "source-location";
    location.textContent = hit.location;
    const excerpt = document.createElement("p");
    excerpt.className = "excerpt";
    excerpt.textContent = hit.text;
    summary.append(title, location);
    details.append(summary, excerpt);
    item.append(details);
    sources.append(item);
  }
  sourceCount.textContent = String(hits.length);
  sourceCount.hidden = hits.length === 0;
  sourcesEmpty.textContent = "No excerpts were retrieved.";
  sourcesEmpty.hidden = hits.length > 0;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submit.disabled) return;
  const value = question.value.trim();
  if (!value) {
    question.focus();
    return;
  }

  submit.disabled = true;
  answer.replaceChildren();
  answer.hidden = true;
  error.hidden = true;
  sources.replaceChildren();
  sourceCount.hidden = true;
  sourcesEmpty.textContent = "Waiting for excerpts…";
  sourcesEmpty.hidden = false;
  status.textContent = "Searching documents and drafting an answer…";
  status.hidden = false;

  try {
    const response = await fetch("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: value }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(typeof payload.detail === "string" ? payload.detail : "The query failed. Try again.");
    }
    const result = await response.json();
    renderSources(result.sources);
    renderAnswer(result.answer, result.sources);
    answer.hidden = false;
    answer.focus();
  } catch (failure) {
    error.textContent = failure.message || "The query failed. Try again.";
    error.hidden = false;
    sourcesEmpty.textContent = "Sources will appear after a successful query.";
  } finally {
    status.hidden = true;
    submit.disabled = false;
  }
});


const uploadInput = document.querySelector("#upload-files");
const dropZone = document.querySelector("#drop-zone");
const uploadStatus = document.querySelector("#upload-status");
const uploadResults = document.querySelector("#upload-results");

dropZone.addEventListener("click", () => uploadInput.click());
uploadInput.addEventListener("change", () => {
  const files = Array.from(uploadInput.files);
  uploadInput.value = "";
  indexFiles(files);
});

dropZone.addEventListener("dragover", (event) => {
  if (!event.dataTransfer.types.includes("Files")) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = dropZone.disabled ? "none" : "copy";
  dropZone.classList.toggle("is-dragging", !dropZone.disabled);
});
dropZone.addEventListener("dragleave", (event) => {
  if (!dropZone.contains(event.relatedTarget)) dropZone.classList.remove("is-dragging");
});
dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("is-dragging");
  indexFiles(Array.from(event.dataTransfer.files));
});

async function requestWithProgress(url, options, bar, label, initialMessage) {
  const id = crypto.randomUUID();
  const separator = url.includes("?") ? "&" : "?";
  const controller = new AbortController();
  let timer;
  bar.hidden = false;
  bar.removeAttribute("value");
  label.hidden = false;
  label.textContent = initialMessage;

  async function poll() {
    try {
      const response = await fetch("/indexing-progress/" + id, {
        cache: "no-store", signal: controller.signal,
      });
      const snapshot = response.ok ? await response.json() : null;
      if (!snapshot || controller.signal.aborted) return;
      const { stage, total, completed, filename, excerpts_done, excerpts_total } = snapshot;
      const phases = { reading: "Reading", embedding: "Embedding", saving: "Saving" };
      if (total && filename) {
        bar.max = total;
        if (total === 1 && !excerpts_total) {
          bar.removeAttribute("value");
        } else {
          bar.value = completed + (excerpts_total ? excerpts_done / excerpts_total : 0);
        }
        const excerptCount = stage === "embedding" ? " · " + excerpts_done + " of " + excerpts_total + " excerpts" : "";
        const message = "File " + (completed + 1) + " of " + total + " · "
          + phases[stage] + " " + filename + excerptCount;
        if (label.textContent !== message) label.textContent = message;
      } else {
        bar.removeAttribute("value");
        label.textContent = stage === "removing" ? "Checking and removing missing entries…" : "Scanning the folder…";
      }
    } catch {
      // The indexing response remains authoritative if a progress poll fails.
    } finally {
      if (!controller.signal.aborted) timer = setTimeout(poll, 500);
    }
  }

  timer = setTimeout(poll, 250);
  try {
    return await fetch(url + separator + "progress_id=" + id, options);
  } finally {
    controller.abort();
    clearTimeout(timer);
    bar.hidden = true;
    label.hidden = true;
  }
}

async function sendUploads(files, allowDuplicate = false) {
  const body = new FormData();
  for (const file of files) body.append("files", file);
  const url = allowDuplicate ? "/ingest?allow_duplicate=true" : "/ingest";
  const response = await requestWithProgress(
    url, { method: "POST", body }, document.querySelector("#upload-progress"),
    document.querySelector("#upload-progress-label"), "Sending files to Atlas…",
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === "string" ? payload.detail : "Upload failed. Please try again.");
  }
  return response.json();
}

function confirmDuplicates(results) {
  const dialog = document.querySelector("#duplicate-dialog");
  const list = document.querySelector("#duplicate-files");
  list.replaceChildren();
  for (const { filename, duplicate_source } of results) {
    const row = document.createElement("li");
    row.textContent = filename + " matches " + sourceName(duplicate_source);
    list.append(row);
  }
  return confirmAction(dialog, "upload");
}

function confirmAction(dialog, expected) {
  dialog.returnValue = "";
  return new Promise((resolve) => {
    dialog.showModal();
    dialog.addEventListener("close", () => resolve(dialog.returnValue === expected), { once: true });
  });
}

async function indexFiles(files) {
  if (!files.length || dropZone.disabled) return;
  dropZone.disabled = true;
  uploadResults.replaceChildren();
  uploadResults.hidden = true;
  uploadStatus.hidden = false;
  const fileLabel = files.length === 1 ? "file" : "files";
  uploadStatus.textContent = "Indexing " + files.length + " " + fileLabel + "…";

  try {
    const results = await sendUploads(files);
    const duplicates = results.flatMap((result, index) => result.duplicate_source ? [index] : []);
    if (duplicates.length) {
      uploadStatus.textContent = "Waiting for your decision on duplicate files…";
      if (await confirmDuplicates(duplicates.map((index) => results[index]))) {
        uploadStatus.textContent = "Indexing the confirmed files…";
        try {
          const retries = await sendUploads(duplicates.map((index) => files[index]), true);
          duplicates.forEach((index, position) => { results[index] = retries[position]; });
        } catch (failure) {
          for (const index of duplicates) {
            results[index] = { filename: results[index].filename, error: failure.message };
          }
        }
      }
    }

    let indexed = 0;
    for (const result of results) {
      const row = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = result.filename;
      const outcome = document.createElement("span");
      if (result.duplicate_source) {
        outcome.textContent = "Duplicate skipped";
      } else if (result.error) {
        outcome.className = "upload-failure";
        outcome.textContent = result.error;
      } else {
        indexed += 1;
        outcome.className = "upload-success";
        outcome.textContent = "Indexed · " + result.chunks + (result.chunks === 1 ? " excerpt" : " excerpts");
      }
      row.append(name, outcome);
      uploadResults.append(row);
    }
    uploadResults.hidden = false;
    uploadStatus.textContent = "Indexed " + indexed + " of " + files.length + " " + fileLabel + "."
      + (indexed ? " You can ask about them now." : "");
  } catch (failure) {
    uploadStatus.textContent = failure.message || "Upload failed. Please try again.";
  } finally {
    dropZone.disabled = false;
    refreshLibrary();
  }
}

const libraryCount = document.querySelector("#library-count");
const libraryStatus = document.querySelector("#library-status");
const libraryDocuments = document.querySelector("#library-documents");
const libraryRefresh = document.querySelector("#library-refresh");
const libraryAction = document.querySelector("#library-action");
const librarySearch = document.querySelector("#library-search");
const libraryMatches = document.querySelector("#library-matches");
const libraryMore = document.querySelector("#library-more");
const libraryLess = document.querySelector("#library-less");
const libraryPageSize = 5;
let libraryLimit = libraryPageSize;
let libraryRows = [];
let libraryRequest;
let deletingDocument = false;

async function deleteIndexedDocument(source, button) {
  if (deletingDocument) return;
  deletingDocument = true;
  const name = sourceName(source);

  try {
    const dialog = document.querySelector("#delete-dialog");
    document.querySelector("#delete-name").textContent = name;
    if (!(await confirmAction(dialog, "delete"))) return;

    button.disabled = true;
    libraryAction.classList.remove("is-error");
    libraryAction.textContent = "Removing " + name + "…";
    const query = new URLSearchParams({ source });
    const response = await fetch("/documents?" + query, { method: "DELETE" });
    if (!response.ok && response.status !== 404) throw new Error("Delete failed");
    libraryAction.textContent = response.status === 404
      ? name + " was already removed from the index."
      : name + " was removed from the index.";
    await refreshLibrary();
    libraryRefresh.focus();
  } catch {
    libraryAction.classList.add("is-error");
    libraryAction.textContent = "Could not remove " + name + ". Try again.";
  } finally {
    button.disabled = false;
    deletingDocument = false;
  }
}

function librarySearchText(value) {
  return value.toLocaleLowerCase("sr").replaceAll("đ", "dj").normalize("NFD").replace(/\p{M}/gu, "");
}

function filterLibrary() {
  const query = librarySearchText(librarySearch.value.trim());
  const visible = query
    ? libraryRows.filter(({ searchable }) => searchable.includes(query))
    : libraryRows.slice(0, libraryLimit);
  libraryDocuments.replaceChildren(...visible.map(({ row }) => row));
  libraryDocuments.hidden = visible.length === 0;
  libraryMatches.hidden = !query;
  libraryMatches.textContent = visible.length
    ? "Showing " + visible.length + " of " + libraryRows.length + " documents."
    : "No indexed documents match your search.";
  libraryMore.hidden = Boolean(query) || libraryLimit >= libraryRows.length;
  libraryLess.hidden = Boolean(query) || visible.length <= libraryPageSize;
}

async function refreshLibrary() {
  libraryRequest?.abort();
  const request = new AbortController();
  libraryRequest = request;
  const timeout = setTimeout(() => request.abort(), 10000);
  libraryStatus.textContent = "Loading indexed documents…";
  try {
    const response = await fetch("/documents", { cache: "no-store", signal: request.signal });
    if (!response.ok) throw new Error("Document list unavailable.");
    const documents = await response.json();
    if (libraryRequest !== request) return;

    libraryRows = documents.map(({ source, chunks }) => {
      const row = document.createElement("li");
      const label = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = sourceName(source);
      const origin = document.createElement("span");
      origin.className = "library-origin";
      const upload = /^uploads\/([a-f0-9]{64})\//.exec(source);
      origin.textContent = upload ? "Browser upload · " + upload[1].slice(0, 8) : (syncedRelativePath(source) ? "Local folder" : source);
      const excerpts = document.createElement("span");
      excerpts.className = "library-excerpts";
      excerpts.textContent = chunks + (chunks === 1 ? " excerpt" : " excerpts");
      const actions = document.createElement("div");
      actions.className = "library-row-actions";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "library-delete";
      remove.textContent = "Delete";
      remove.setAttribute("aria-label", "Delete " + name.textContent + " from the index");
      remove.addEventListener("click", () => deleteIndexedDocument(source, remove));
      actions.append(excerpts, remove);
      label.append(name, origin);
      row.append(label, actions);
      const searchPath = syncedRelativePath(source) || (upload ? name.textContent : source);
      return { row, searchable: librarySearchText(searchPath) };
    });
    librarySearch.disabled = false;
    filterLibrary();
    libraryCount.textContent = String(libraryRows.length);
    libraryCount.hidden = false;
    libraryStatus.textContent = libraryRows.length
      ? "Available to query with the current embedding model."
      : "No documents indexed for the current embedding model.";
  } catch {
    if (libraryRequest !== request) return;
    librarySearch.disabled = true;
    libraryMatches.hidden = true;
    libraryMore.hidden = true;
    libraryLess.hidden = true;
    libraryCount.hidden = true;
    libraryDocuments.hidden = true;
    libraryStatus.textContent = "Could not load indexed documents. Try refreshing the list.";
  } finally {
    clearTimeout(timeout);
  }
}

libraryRefresh.addEventListener("click", refreshLibrary);
librarySearch.addEventListener("input", filterLibrary);
libraryMore.addEventListener("click", () => {
  libraryLimit += libraryPageSize;
  filterLibrary();
  if (libraryMore.hidden) libraryLess.focus();
});
libraryLess.addEventListener("click", () => {
  libraryLimit = libraryPageSize;
  filterLibrary();
  libraryMore.focus();
});
refreshLibrary();

const syncRun = document.querySelector("#sync-run");
const syncRemove = document.querySelector("#sync-remove");
const syncStatus = document.querySelector("#sync-status");
const syncDetails = document.querySelector("#sync-details");

async function loadSyncConfiguration() {
  try {
    const response = await fetch("/sync", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not check folder configuration.");
    const { configured } = await response.json();
    syncRun.disabled = !configured;
    syncStatus.textContent = configured
      ? "Index changes from your local OneDrive folder and its subfolders."
      : "Choose a document folder in Podešavanja.";
  } catch {
    syncStatus.textContent = "Could not check folder configuration. Reload the page to try again.";
  }
}

async function syncFolder(removeMissing = false) {
  syncRun.disabled = true;
  syncRemove.hidden = true;
  syncStatus.textContent = "Scanning and indexing the folder…";
  syncDetails.replaceChildren();
  syncDetails.hidden = true;
  try {
    const response = await requestWithProgress(
      removeMissing ? "/sync?remove_missing=true" : "/sync", { method: "POST" },
      document.querySelector("#sync-progress"), document.querySelector("#sync-progress-label"), "Scanning the folder…",
    );
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(typeof payload.detail === "string" ? payload.detail : "Folder sync failed.");
    }
    const report = await response.json();
    const issues = Object.entries(report.errors);
    const duplicates = Object.entries(report.duplicates || {});
    syncStatus.textContent = [
      report.added + " added", report.modified + " updated", report.unchanged + " unchanged",
      report.deleted + " removed", report.missing.length + " missing",
      ...(duplicates.length ? [duplicates.length + " duplicates skipped"] : []),
      ...(issues.length ? [issues.length + " issues. Unverified entries were kept."] : []),
    ].join(" · ");
    for (const [path, reason] of issues) {
      const row = document.createElement("li");
      row.textContent = path === "." ? reason : path + " — " + reason;
      syncDetails.append(row);
    }
    for (const [copy, kept] of duplicates) {
      const row = document.createElement("li");
      row.textContent = copy + " — same file as " + kept;
      syncDetails.append(row);
    }
    for (const path of report.missing) {
      const row = document.createElement("li");
      row.textContent = path + " — missing locally";
      syncDetails.append(row);
    }
    syncDetails.hidden = !syncDetails.childElementCount;
    syncRemove.hidden = issues.length > 0 || report.missing.length === 0;
  } catch (failure) {
    syncStatus.textContent = failure.message || "Folder sync failed. Try again.";
  } finally {
    syncRun.disabled = false;
    refreshLibrary();
  }
}

syncRun.addEventListener("click", () => syncFolder());
syncRemove.addEventListener("click", async () => {
  const dialog = document.querySelector("#sync-dialog");
  if (await confirmAction(dialog, "remove")) await syncFolder(true);
});
loadSyncConfiguration();

const settingsOpen = document.querySelector("#settings-open");
const settingsDialog = document.querySelector("#settings-dialog");
const settingsForm = document.querySelector("#settings-form");
const settingsKey = document.querySelector("#settings-key");
const settingsFolder = document.querySelector("#settings-folder");
const settingsBrowse = document.querySelector("#settings-browse");
const settingsSave = document.querySelector("#settings-save");
const settingsStatus = document.querySelector("#settings-status");
const settingsKeyState = document.querySelector("#settings-key-state");

function applySettings(settings) {
  settingsKey.value = "";
  settingsFolder.value = settings.document_folder;
  settingsBrowse.hidden = !settings.can_browse;
  settingsKeyState.textContent = settings.key_configured
    ? "Ključ je podešen. Unesite ključ samo ako želite da ga zamenite."
    : "Ključ još nije podešen.";
  settingsOpen.classList.toggle("setup-needed", !settings.key_configured);
}

settingsOpen.addEventListener("click", () => {
  settingsStatus.textContent = "";
  if (!settingsDialog.open) settingsDialog.showModal();
});
document.querySelector("#settings-close").addEventListener("click", () => settingsDialog.close());
settingsDialog.addEventListener("close", () => { settingsKey.value = ""; });
settingsBrowse.addEventListener("click", async () => {
  settingsBrowse.disabled = true;
  try {
    const response = await fetch("/settings/browse", { method: "POST" });
    if (!response.ok) throw new Error("Otvaranje fascikle nije uspelo. Nalepite putanju u polje.");
    const { folder } = await response.json();
    if (folder) settingsFolder.value = folder;
  } catch (error) {
    settingsStatus.textContent = error.message;
  } finally {
    settingsBrowse.disabled = false;
  }
});
settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (settingsSave.disabled) return;
  settingsSave.disabled = true;
  settingsStatus.textContent = "Čuvanje…";
  try {
    const response = await fetch("/settings", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: settingsKey.value || null, document_folder: settingsFolder.value }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === "string" ? error.detail : "Čuvanje nije uspelo. Proverite unete podatke.");
    }
    const settings = await response.json();
    applySettings(settings);
    settingsStatus.textContent = "Podešavanja su sačuvana.";
    loadSyncConfiguration();
  } catch (error) {
    settingsStatus.textContent = error.message || "Čuvanje nije uspelo. Pokušajte ponovo.";
  } finally {
    settingsSave.disabled = false;
  }
});

async function loadSettings() {
  try {
    const response = await fetch("/settings", { cache: "no-store" });
    if (!response.ok) return;
    const settings = await response.json();
    applySettings(settings);
    settingsOpen.hidden = false;
    if (!settings.key_configured && !settingsDialog.open) settingsDialog.showModal();
  } catch {
    // Existing upload and query errors still show when settings cannot be loaded.
  }
}
loadSettings();
