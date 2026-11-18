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

async function indexFiles(files) {
  if (!files.length || dropZone.disabled) return;
  const body = new FormData();
  for (const file of files) body.append("files", file);

  dropZone.disabled = true;
  uploadResults.replaceChildren();
  uploadResults.hidden = true;
  uploadStatus.hidden = false;
  const fileLabel = files.length === 1 ? "file" : "files";
  uploadStatus.textContent = "Indexing " + files.length + " " + fileLabel + "…";

  try {
    const response = await fetch("/ingest", { method: "POST", body });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(typeof payload.detail === "string" ? payload.detail : "Upload failed. Please try again.");
    }
    const results = await response.json();
    let indexed = 0;
    for (const result of results) {
      const row = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = result.filename;
      const outcome = document.createElement("span");
      if (result.error) {
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
  }
}
