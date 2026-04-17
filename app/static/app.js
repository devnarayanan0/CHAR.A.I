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
const activityTable = document.getElementById("activity-table");

let activityRefreshTimer = null;

function showPage(page) {
  const ingestionActive = page === "ingestion";
  pageIngestion.classList.toggle("hidden", !ingestionActive);
  pageActivity.classList.toggle("hidden", ingestionActive);

  navIngestion.className = ingestionActive
    ? "rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white"
    : "rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700";

  navActivity.className = !ingestionActive
    ? "rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white"
    : "rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700";

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
  ingestionSpinner.classList.remove("hidden");
  ingestionSuccess.classList.add("hidden");
  ingestionState.textContent = "Processing...";
  ingestionStatus.textContent = "PROCESSING";

  try {
    const response = await fetch("/admin/ingest", { method: "POST" });
    const result = await response.json();

    if (!response.ok) {
      throw new Error(result.detail || "Ingestion failed");
    }

    processedFiles.textContent = String(result.processed_files ?? 0);
    uploadedChunks.textContent = String(result.uploaded_chunks ?? 0);
    ingestionStatus.textContent = String(result.status || "SUCCESS").toUpperCase();
    ingestionState.textContent = "Completed";
    ingestionSuccess.classList.remove("hidden");
  } catch (error) {
    ingestionState.textContent = error.message;
    ingestionStatus.textContent = "FAILED";
  } finally {
    runIngestionButton.disabled = false;
    ingestionSpinner.classList.add("hidden");
  }
}

function renderActivityRows(logs) {
  if (!Array.isArray(logs) || logs.length === 0) {
    activityTable.innerHTML = `
      <tr>
        <td colspan="2" class="px-4 py-6 text-center text-sm text-slate-500">No activity yet.</td>
      </tr>
    `;
    return;
  }

  activityTable.innerHTML = logs
    .map(
      (log) => `
        <tr>
          <td class="px-4 py-3 text-sm text-slate-800">${log.user || "unknown"}</td>
          <td class="px-4 py-3 text-sm text-slate-600">${new Date(log.timestamp).toLocaleString()}</td>
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
        <td colspan="2" class="px-4 py-6 text-center text-sm text-red-600">${error.message}</td>
      </tr>
    `;
  }
}

navIngestion.addEventListener("click", () => showPage("ingestion"));
navActivity.addEventListener("click", () => showPage("activity"));
runIngestionButton.addEventListener("click", runIngestion);

showPage("ingestion");
