const navIngestion = document.getElementById("nav-ingestion");
const navActivity = document.getElementById("nav-activity");
const pageIngestion = document.getElementById("page-ingestion");
const pageActivity = document.getElementById("page-activity");
const runIngestionButton = document.getElementById("run-ingestion");
const ingestionSpinner = document.getElementById("ingestion-spinner");
const ingestionState = document.getElementById("ingestion-state");
const ingestionSuccess = document.getElementById("ingestion-success");
const processedFiles = document.getElementById("processed-files");
const uploadedChunks = document.getElementById("uploaded-chunks");
const ingestionStatus = document.getElementById("ingestion-status");
const statusDot = document.getElementById("status-dot");
const activityTable = document.getElementById("activity-table");

let activityRefreshTimer = null;

function showPage(page) {
  const ingestionActive = page === "ingestion";
  pageIngestion.classList.toggle("active", ingestionActive);
  pageActivity.classList.toggle("active", !ingestionActive);
  navIngestion.classList.toggle("active", ingestionActive);
  navActivity.classList.toggle("active", !ingestionActive);

  if (ingestionActive) {
    if (activityRefreshTimer) {
      window.clearInterval(activityRefreshTimer);
      activityRefreshTimer = null;
    }
    return;
  }

  loadActivity();
  if (!activityRefreshTimer) {
    activityRefreshTimer = window.setInterval(loadActivity, 8000);
  }
}

async function runIngestion() {
  runIngestionButton.disabled = true;
  ingestionSpinner.style.display = "block";
  ingestionSuccess.style.display = "none";
  ingestionState.textContent = "Processing...";
  ingestionStatus.textContent = "Running";
  statusDot.className = "status-dot running";

  try {
    const response = await fetch("/admin/ingest", { method: "POST" });
    const result = await response.json();

    if (!response.ok) {
      throw new Error(result.detail || "Ingestion failed");
    }

    processedFiles.textContent = String(result.processed_files ?? 0);
    uploadedChunks.textContent = String(result.uploaded_chunks ?? 0);
      ingestionStatus.textContent = String(result.status || "SUCCESS");
      ingestionState.textContent = "Last run: just now";
      statusDot.className = "status-dot done";
      ingestionSuccess.style.display = "flex";
  } catch (error) {
    ingestionState.textContent = error.message;
    ingestionStatus.textContent = "FAILED";
      statusDot.className = "status-dot";
  } finally {
    runIngestionButton.disabled = false;
      ingestionSpinner.style.display = "none";
  }
}

function renderActivityRows(groups) {
  if (!Array.isArray(groups) || groups.length === 0) {
    activityTable.innerHTML = `
      <div class="empty-cell">No user logs yet.</div>
    `;
    return;
  }

  const escapeHtml = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");

  activityTable.innerHTML = groups
    .map((group) => {
      const userName = escapeHtml(group.name || "Unknown");
      const phone = escapeHtml(group.phone || "-");
      const email = escapeHtml(group.email || "-");
      const lastActivity = group.last_activity
        ? escapeHtml(new Date(group.last_activity).toLocaleString())
        : "-";
      const messages = Array.isArray(group.messages) ? group.messages : [];

      const logItems = messages.length
        ? messages
            .map((entry) => {
              const role = String(entry.role || "assistant").toLowerCase();
              const roleLabel = role === "user" ? "User" : "Assistant";
              const content = escapeHtml(entry.content || "(empty message)");
              const timestamp = entry.time
                ? escapeHtml(new Date(entry.time).toLocaleString())
                : "-";
              return `
                <li class="log-item">
                  <div class="log-role">${roleLabel}</div>
                  <div class="log-question">${content}</div>
                  <div class="log-time">${timestamp}</div>
                </li>
              `;
            })
            .join("")
        : '<li class="log-item"><div class="log-question">No messages yet.</div></li>';

      return `
        <details class="user-log-card">
          <summary>
            <div class="user-log-header">
              <div class="user-log-name">${userName}</div>
              <div class="user-log-meta">Phone: ${phone} • Email: ${email} • Last activity: ${lastActivity} • Messages: ${messages.length}</div>
            </div>
          </summary>
          <ul class="log-list">${logItems}</ul>
        </details>
      `;
    })
    .join("");
}

async function loadActivity() {
  try {
    const response = await fetch("/admin/logs");
    const logs = await response.json();

    if (!response.ok) {
      throw new Error("Failed to load activity");
    }

    renderActivityRows(logs);
  } catch (error) {
    activityTable.innerHTML = `
      <div class="empty-cell">${error.message}</div>
    `;
  }
}

navIngestion.addEventListener("click", () => showPage("ingestion"));
navActivity.addEventListener("click", () => showPage("activity"));
runIngestionButton.addEventListener("click", runIngestion);

showPage("ingestion");
