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

function renderActivityRows(logs) {
  if (!Array.isArray(logs) || logs.length === 0) {
    activityTable.innerHTML = `
      <tr>
          <td colspan="3" class="empty-cell">No activity yet.</td>
      </tr>
    `;
    return;
  }

  activityTable.innerHTML = logs
    .map(
      (log) => `
        <tr>
            <td>${log.user || "unknown"}</td>
            <td>${new Date(log.timestamp).toLocaleString()}</td>
            <td><span class="pill pill-green"><span class="pill-dot"></span>${log.state || "UNKNOWN"}</span></td>
        </tr>
      `,
    )
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
      <tr>
          <td colspan="3" class="empty-cell">${error.message}</td>
      </tr>
    `;
  }
}

navIngestion.addEventListener("click", () => showPage("ingestion"));
navActivity.addEventListener("click", () => showPage("activity"));
runIngestionButton.addEventListener("click", runIngestion);

showPage("ingestion");
