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
const messageCache = new Map();

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatTimestamp(value) {
  if (!value) {
    return "-";
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? escapeHtml(value) : escapeHtml(parsed.toLocaleString());
}

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

async function loadConversation(phone, bodyElement) {
  const cacheKey = String(phone || "").trim();
  if (!cacheKey) {
    return;
  }

  if (messageCache.has(cacheKey)) {
    renderConversationBody(bodyElement, messageCache.get(cacheKey));
    return;
  }

  bodyElement.innerHTML = '<div class="empty-cell">Loading messages...</div>';

  const response = await fetch(`/admin/logs/${encodeURIComponent(cacheKey)}`);
  const messages = await response.json();

  if (!response.ok) {
    throw new Error("Failed to load user messages");
  }

  messageCache.set(cacheKey, Array.isArray(messages) ? messages : []);
  renderConversationBody(bodyElement, messageCache.get(cacheKey));
}

function renderConversationBody(bodyElement, messages) {
  if (!Array.isArray(messages) || messages.length === 0) {
    bodyElement.innerHTML = '<div class="empty-cell">No messages for this user yet.</div>';
    return;
  }

  bodyElement.innerHTML = `
    <ul class="conversation-list">
      ${messages
        .map((entry) => {
          const role = String(entry.role || "assistant").toLowerCase();
          const roleLabel = role === "user" ? "User" : "Assistant";
          const turnClass = role === "user" ? "turn-user" : "turn-assistant";
          return `
            <li class="conversation-turn ${turnClass}">
              <div class="conversation-role">${roleLabel}</div>
              <div class="conversation-content">${escapeHtml(entry.content || "(empty message)")}</div>
              <div class="conversation-time">${formatTimestamp(entry.created_at)}</div>
            </li>
          `;
        })
        .join("")}
    </ul>
  `;
}

function bindExpandableCards() {
  activityTable.querySelectorAll(".user-log-card").forEach((card) => {
    if (card.dataset.bound === "1") {
      return;
    }

    card.dataset.bound = "1";
    card.addEventListener("toggle", async () => {
      if (!card.open || card.dataset.loaded === "1") {
        return;
      }

      const phone = card.dataset.phone || "";
      const bodyElement = card.querySelector("[data-conversation-body]");
      if (!(bodyElement instanceof HTMLElement)) {
        return;
      }

      try {
        await loadConversation(phone, bodyElement);
        card.dataset.loaded = "1";
      } catch (error) {
        bodyElement.innerHTML = `<div class="empty-cell">${escapeHtml(error.message)}</div>`;
      }
    });
  });
}

function renderActivityRows(groups) {
  if (!Array.isArray(groups) || groups.length === 0) {
    activityTable.innerHTML = `
      <div class="empty-cell">No user logs yet.</div>
    `;
    return;
  }

  activityTable.innerHTML = groups
    .map((group) => {
      const phone = escapeHtml(group.phone || "-");
      const lastActivity = formatTimestamp(group.last_activity);
      const messageCount = Number(group.message_count ?? 0);

      return `
        <details class="user-log-card" data-phone="${phone}">
          <summary>
            <div class="user-log-header">
              <div class="user-log-name">${phone}</div>
              <div class="user-log-meta">Last activity: ${lastActivity} • Messages: ${messageCount}</div>
            </div>
            <div class="user-log-toggle">▾</div>
          </summary>
          <div class="conversation-shell" data-conversation-body>
            <div class="empty-cell">Click to load messages.</div>
          </div>
        </details>
      `;
    })
    .join("");

  bindExpandableCards();
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
      <div class="empty-cell">${escapeHtml(error.message)}</div>
    `;
  }
}

navIngestion.addEventListener("click", () => showPage("ingestion"));
navActivity.addEventListener("click", () => showPage("activity"));
runIngestionButton.addEventListener("click", runIngestion);

showPage("ingestion");
