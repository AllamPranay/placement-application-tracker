/*
 * Placement Application Tracker — frontend logic in plain JavaScript (no framework).
 *
 * Every feature follows the same loop:
 *   user action (click / type / submit)
 *     -> fetch() a JSON endpoint of the FastAPI backend
 *     -> read the JSON reply
 *     -> update the page (the DOM)
 *
 * Safety note: text coming from the server is always written with `textContent`,
 * never `innerHTML`, so a company name like "<script>" is shown, not executed (no XSS).
 */

// ===================== 1. Constants and page elements =====================

const STATUSES = ["Wishlist", "Applied", "OA", "Interview", "Offer", "Rejected"];
const FUNNEL_STAGES = ["Applied", "OA", "Interview", "Offer"];
const DUE_SOON_DAYS = 3; // highlight rows whose next step is this close

// Grab the elements we update often, once, at start-up.
const form = document.getElementById("application-form");
const formTitle = document.getElementById("form-title");
const submitButton = document.getElementById("submit-button");
const cancelEditButton = document.getElementById("cancel-edit");
const formError = document.getElementById("form-error");
const searchInput = document.getElementById("search");
const statusFilter = document.getElementById("filter-status");
const sortSelect = document.getElementById("sort");
const tableBody = document.getElementById("applications-body");
const emptyMessage = document.getElementById("empty-message");
const historyDialog = document.getElementById("history-dialog");
const toast = document.getElementById("toast");

// Page state: the rows currently shown, and which application (if any) is being edited.
let currentApplications = [];
let editingId = null;

// ===================== 2. Small helpers =====================

/** Call the backend and return parsed JSON. Throws an Error with a readable message. */
async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (response.status === 204) return null; // 204 No Content has no body
  const data = await response.json().catch(() => null); // null if the body is not JSON
  if (!response.ok) {
    throw new Error(data ? errorText(data.detail) : `Request failed (HTTP ${response.status})`);
  }
  return data;
}

/** FastAPI errors are either a string or a list of {loc, msg}; turn both into one sentence. */
function errorText(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((err) => {
        const field = err.loc[err.loc.length - 1];
        const message = err.msg.replace(/^Value error, /, "");
        return field === "body" ? message : `${field}: ${message}`;
      })
      .join("; ");
  }
  return "Something went wrong";
}

/** Show a short message at the bottom of the screen for 3 seconds. */
let toastTimer;
function showToast(message, isError = false) {
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.hidden = true), 3000);
}

/** "2026-10-30" -> Date at local midnight (new Date("2026-10-30") would use UTC). */
function parseDate(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day);
}

/** Whole days from today until the given date (negative if it is in the past). */
function daysUntil(isoDate) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((parseDate(isoDate) - today) / 86_400_000); // ms in a day
}

/** "2026-10-30" -> "30 Oct 2026" */
function formatDate(isoDate) {
  return parseDate(isoDate).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** 0 -> "Today", 1 -> "Tomorrow", 3 -> "In 3 days" */
function relativeDay(days) {
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  return `In ${days} days`;
}

/** Create an element with optional class and text — saves a lot of repetition. */
function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

/** Fill a <select> with one <option> per status. */
function addStatusOptions(select) {
  for (const status of STATUSES) {
    select.append(new Option(status, status));
  }
}

// ===================== 3. Stats cards + funnel chart =====================

async function loadStats() {
  const stats = await api("/api/stats");
  renderStats(stats);
  renderFunnel(stats.funnel);
}

function renderStats(stats) {
  document.getElementById("stat-total").textContent = stats.total;
  document.getElementById("stat-active").textContent = stats.active;
  document.getElementById("stat-offers").textContent = stats.by_status.Offer;
  document.getElementById("stat-upcoming").textContent = stats.upcoming_7_days;
  document.getElementById("stat-offer-ctc").textContent =
    stats.avg_offer_ctc_lpa === null ? "Average CTC: –" : `Average CTC: ${stats.avg_offer_ctc_lpa} LPA`;
  document.getElementById("header-counts").textContent =
    `${stats.total} applications · ${stats.active} active · ${stats.by_status.Offer} offers`;
}

/** Draw the funnel: each bar is a <div> whose width is a percentage of the first stage. */
function renderFunnel(funnel) {
  const container = document.getElementById("funnel");
  container.replaceChildren(); // remove the old bars
  const largest = Math.max(funnel.reached.Applied, 1); // avoid dividing by zero
  const conversions = [funnel.applied_to_oa_pct, funnel.oa_to_interview_pct, funnel.interview_to_offer_pct];

  FUNNEL_STAGES.forEach((stage, index) => {
    const count = funnel.reached[stage];

    const row = createElement("div", "funnel-row");
    row.title = `${stage}: ${count} application(s) reached this stage`; // hover tooltip
    const track = createElement("div", "funnel-track");
    const bar = createElement("div", "funnel-bar");
    bar.style.width = `${(count / largest) * 100}%`;
    track.append(bar);
    row.append(createElement("span", "funnel-label", stage), track, createElement("span", "funnel-count", count));
    container.append(row);

    // Between two bars, show how many moved on to the next stage.
    if (index < conversions.length) {
      const next = FUNNEL_STAGES[index + 1];
      container.append(createElement("p", "funnel-step", `↓ ${conversions[index]}% moved on to ${next}`));
    }
  });
}

// ===================== 4. Applications table =====================

// Counts table requests, so a slow, out-of-date reply can't overwrite a newer one.
let latestTableRequest = 0;

/** Read the filter controls, ask the API for matching rows, then draw them. */
async function loadApplications() {
  const params = new URLSearchParams({ sort: sortSelect.value });
  if (statusFilter.value) params.set("status", statusFilter.value);
  if (searchInput.value.trim()) params.set("q", searchInput.value.trim());

  const requestNumber = ++latestTableRequest;
  const applications = await api(`/api/applications?${params}`);
  if (requestNumber !== latestTableRequest) return; // a newer request was sent meanwhile: ignore this reply
  currentApplications = applications;
  renderTable(applications);
}

function renderTable(applications) {
  tableBody.replaceChildren(...applications.map(buildRow));
  const filtersActive = statusFilter.value || searchInput.value.trim();
  emptyMessage.hidden = applications.length > 0;
  emptyMessage.textContent = filtersActive
    ? "No applications match your filters."
    : "No applications yet — add your first one with the form.";
}

/** Build one <tr> for an application. */
function buildRow(app) {
  const row = document.createElement("tr");
  row.dataset.id = app.id; // lets click handlers know which application a button belongs to

  // Company (linked if we have a job link), role, location, notes
  const companyCell = document.createElement("td");
  const company = createElement("div", "company");
  if (app.job_link) {
    const link = createElement("a", "", app.company);
    link.href = app.job_link;
    link.target = "_blank";
    link.rel = "noopener";
    company.append(link);
  } else {
    company.textContent = app.company;
  }
  const roleText = app.location ? `${app.role} · ${app.location}` : app.role;
  companyCell.append(company, createElement("div", "role", roleText));
  if (app.notes) {
    const notes = createElement("div", "notes", app.notes);
    notes.title = app.notes;
    companyCell.append(notes);
  }

  // Inline status dropdown: changing it calls PATCH /status straight away
  const statusCell = document.createElement("td");
  const statusSelect = createElement("select", "status-select");
  statusSelect.dataset.status = app.status; // CSS colours the pill by this attribute
  statusSelect.setAttribute("aria-label", `Status of ${app.company}`);
  addStatusOptions(statusSelect);
  statusSelect.value = app.status;
  statusCell.append(statusSelect);

  const ctcCell = createElement("td", "num", app.ctc_lpa === null ? "–" : `${app.ctc_lpa} LPA`);
  const appliedCell = createElement("td", "date", app.applied_on ? formatDate(app.applied_on) : "–");

  // Next step date, plus a "Today / Tomorrow / In N days" tag when it is close
  const nextCell = createElement("td", "date");
  if (app.next_step_date) {
    nextCell.textContent = formatDate(app.next_step_date);
    const days = daysUntil(app.next_step_date);
    if (days >= 0 && days <= DUE_SOON_DAYS && app.status !== "Rejected") {
      row.classList.add("due-soon");
      nextCell.append(createElement("div", "due-tag", relativeDay(days)));
    }
  } else {
    nextCell.append(createElement("span", "muted", "–"));
  }

  // Action buttons; data-action tells the shared click handler what to do
  const actionsCell = document.createElement("td");
  const actions = createElement("div", "actions");
  for (const [action, label, extraClass] of [
    ["history", "History", ""],
    ["edit", "Edit", ""],
    ["delete", "Delete", "danger"],
  ]) {
    const button = createElement("button", `button ghost small ${extraClass}`.trim(), label);
    button.type = "button";
    button.dataset.action = action;
    button.setAttribute("aria-label", `${label} ${app.company}`);
    actions.append(button);
  }
  actionsCell.append(actions);

  row.append(companyCell, statusCell, ctcCell, appliedCell, nextCell, actionsCell);
  return row;
}

// ===================== 5. Add / edit form =====================

/** Collect the form into the JSON shape the API expects (empty inputs become null). */
function readForm() {
  const value = (name) => form.elements[name].value.trim() || null;
  const ctc = value("ctc_lpa");
  return {
    company: value("company"),
    role: value("role"),
    location: value("location"),
    ctc_lpa: ctc === null ? null : Number(ctc),
    status: form.elements.status.value,
    applied_on: value("applied_on"),
    next_step_date: value("next_step_date"),
    job_link: value("job_link"),
    notes: value("notes"),
  };
}

/** Client-side checks (the server checks again — never trust the browser alone). */
function validate(data) {
  const errors = {};
  if (!data.company) errors.company = "Company is required.";
  if (!data.role) errors.role = "Role is required.";
  if (data.ctc_lpa !== null && (Number.isNaN(data.ctc_lpa) || data.ctc_lpa < 0)) {
    errors.ctc_lpa = "CTC must be a number ≥ 0.";
  }
  if (data.job_link && !/^https?:\/\/\S+$/.test(data.job_link)) {
    errors.job_link = "Link must start with http:// or https://";
  }
  // ISO dates ("2026-10-30") compare correctly as plain strings
  if (data.applied_on && data.next_step_date && data.next_step_date < data.applied_on) {
    errors.next_step_date = "Next step can't be before the applied date.";
  }
  return errors;
}

/** Put each error message under its field (and clear old ones). */
function showFieldErrors(errors) {
  for (const name of ["company", "role", "ctc_lpa", "job_link", "next_step_date"]) {
    document.getElementById(`error-${name}`).textContent = errors[name] || "";
    form.elements[name].setAttribute("aria-invalid", errors[name] ? "true" : "false");
  }
}

/** Switch the form into "edit" mode and fill it with an application's values. */
function startEdit(app) {
  editingId = app.id;
  for (const name of ["company", "role", "location", "ctc_lpa", "status", "applied_on", "next_step_date", "job_link", "notes"]) {
    form.elements[name].value = app[name] ?? ""; // ?? turns null into ""
  }
  formTitle.textContent = `Edit: ${app.company}`;
  submitButton.textContent = "Save changes";
  cancelEditButton.hidden = false;
  showFieldErrors({});
  formError.textContent = "";
  form.scrollIntoView({ behavior: "smooth", block: "start" });
  form.elements.company.focus({ preventScroll: true });
}

/** Back to an empty "add" form. */
function resetForm() {
  editingId = null;
  form.reset();
  form.elements.status.value = "Applied"; // most new entries are already applied
  formTitle.textContent = "Add application";
  submitButton.textContent = "Add application";
  cancelEditButton.hidden = true;
  showFieldErrors({});
  formError.textContent = "";
}

async function handleSubmit(event) {
  event.preventDefault(); // stop the browser from reloading the page
  const data = readForm();
  const errors = validate(data);
  showFieldErrors(errors);
  if (Object.keys(errors).length > 0) return;

  submitButton.disabled = true;
  try {
    if (editingId === null) {
      await api("/api/applications", { method: "POST", body: JSON.stringify(data) });
      showToast(`Added ${data.company}`);
    } else {
      await api(`/api/applications/${editingId}`, { method: "PUT", body: JSON.stringify(data) });
      showToast(`Saved ${data.company}`);
    }
    resetForm();
    await refresh();
  } catch (error) {
    formError.textContent = error.message; // e.g. a 422 message from the server
  } finally {
    submitButton.disabled = false;
  }
}

// ===================== 6. Row actions: status, delete, history =====================

async function changeStatus(app, newStatus, select) {
  try {
    await api(`/api/applications/${app.id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status: newStatus }),
    });
    showToast(`${app.company}: ${app.status} → ${newStatus}`);
    await refresh();
  } catch (error) {
    select.value = app.status; // put the dropdown back
    showToast(error.message, true);
  }
}

async function deleteApplication(app) {
  if (!confirm(`Delete ${app.company} – ${app.role}? This also deletes its history.`)) return;
  try {
    await api(`/api/applications/${app.id}`, { method: "DELETE" });
    if (editingId === app.id) resetForm();
    showToast(`Deleted ${app.company}`);
    await refresh();
  } catch (error) {
    showToast(error.message, true);
  }
}

/** Load the status timeline and open it in the <dialog>. */
async function showHistory(app) {
  try {
    const history = await api(`/api/applications/${app.id}/history`);
    document.getElementById("history-title").textContent = `${app.company}`;
    document.getElementById("history-subtitle").textContent = `${app.role} — status timeline`;
    const list = document.getElementById("history-list");
    list.replaceChildren();
    for (const entry of history) {
      const item = document.createElement("li");
      if (entry.from_status === null) {
        item.append("Created as ");
      } else {
        item.append(createPill(entry.from_status), " → ");
      }
      item.append(createPill(entry.to_status));
      const time = createElement("time", "", new Date(entry.changed_at).toLocaleString("en-IN", {
        dateStyle: "medium",
        timeStyle: "short",
      }));
      time.dateTime = entry.changed_at;
      item.append(time);
      list.append(item);
    }
    historyDialog.showModal();
  } catch (error) {
    showToast(error.message, true);
  }
}

function createPill(status) {
  const pill = createElement("span", "pill", status);
  pill.dataset.status = status;
  return pill;
}

// ===================== 7. Wire up events and load data =====================

/** Reload stats and table together (Promise.all runs both requests in parallel). */
async function refresh() {
  try {
    await Promise.all([loadStats(), loadApplications()]);
  } catch (error) {
    showToast(`Could not load data: ${error.message}`, true);
  }
}

form.addEventListener("submit", handleSubmit);
cancelEditButton.addEventListener("click", resetForm);

// Filters: reload the table whenever they change.
statusFilter.addEventListener("change", loadApplications);
sortSelect.addEventListener("change", loadApplications);

// Search: wait until the user stops typing for 250 ms ("debounce") to avoid a request per key.
let searchTimer;
searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadApplications, 250);
});

// Event delegation: ONE listener on <tbody> handles the buttons of every row,
// even rows created later. We find the row, then the application it belongs to.
tableBody.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const id = Number(button.closest("tr").dataset.id);
  const app = currentApplications.find((a) => a.id === id);
  if (button.dataset.action === "edit") startEdit(app);
  if (button.dataset.action === "delete") deleteApplication(app);
  if (button.dataset.action === "history") showHistory(app);
});

tableBody.addEventListener("change", (event) => {
  if (!event.target.matches(".status-select")) return;
  const id = Number(event.target.closest("tr").dataset.id);
  const app = currentApplications.find((a) => a.id === id);
  changeStatus(app, event.target.value, event.target);
});

// Start-up: fill the status dropdowns, reset the form, load everything.
addStatusOptions(form.elements.status);
addStatusOptions(statusFilter);
resetForm();
refresh();
