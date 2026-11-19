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

function sourceName(path) {
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
    title.title = hit.source;
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

async function sendUploads(files, allowDuplicate = false) {
  const body = new FormData();
  for (const file of files) body.append("files", file);
  const url = allowDuplicate ? "/ingest?allow_duplicate=true" : "/ingest";
  const response = await fetch(url, { method: "POST", body });
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

    const rows = documents.map(({ source, chunks }) => {
      const row = document.createElement("li");
      const label = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = sourceName(source);
      const origin = document.createElement("span");
      origin.className = "library-origin";
      const upload = /^uploads\/([a-f0-9]{64})\//.exec(source);
      origin.textContent = upload ? "Browser upload · " + upload[1].slice(0, 8) : source;
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
      return row;
    });
    libraryDocuments.replaceChildren(...rows);
    libraryDocuments.hidden = !rows.length;
    libraryCount.textContent = String(rows.length);
    libraryCount.hidden = false;
    libraryStatus.textContent = rows.length
      ? "Available to query with the current embedding model."
      : "No documents indexed for the current embedding model.";
  } catch {
    if (libraryRequest !== request) return;
    libraryCount.hidden = true;
    libraryDocuments.hidden = true;
    libraryStatus.textContent = "Could not load indexed documents. Try refreshing the list.";
  } finally {
    clearTimeout(timeout);
  }
}

libraryRefresh.addEventListener("click", refreshLibrary);
refreshLibrary();
