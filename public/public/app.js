// PUMA AUTOMATION SUITE JAVASCRIPT LOGIC

// Set this to your live Render backend URL if Vercel file upload sizes exceed 4.5 MB
// Example: const API_BASE = "https://puma-automation.onrender.com";
const API_BASE = "";

document.addEventListener("DOMContentLoaded", () => {
    initTabNavigation();
    initEventListeners();
});

// Stateless variables to hold session results in client-side memory
let currentReportBase64 = null;
let currentReportName = null;
let currentQCBase64 = null;
let currentQCName = null;

let currentOrderReportBase64 = null;
let currentOrderReportName = null;
let currentSellerGroups = null; // Holds seller group records
let currentDiscrepanciesAll = null; // Holds all discrepancy records

let currentLQCReportBase64 = null;
let currentLQCReportName = null;
let currentLQCValDf = null; // Holds validated listings data for comparison
let currentLQCSyncBase64 = null;
let currentLQCSyncName = null;

// ================= TAB NAVIGATION =================
function initTabNavigation() {
    const navButtons = document.querySelectorAll(".nav-btn");
    const tabContents = document.querySelectorAll(".tab-content");
    const contextPanels = document.querySelectorAll(".context-panel");

    navButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            // Update active button
            navButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            // Toggle tab content
            const targetTab = btn.getAttribute("data-tab");
            tabContents.forEach(tab => {
                if (tab.id === targetTab) {
                    tab.classList.remove("hidden");
                } else {
                    tab.classList.add("hidden");
                }
            });

            // Toggle sidebar config panels
            contextPanels.forEach(panel => {
                panel.classList.add("hidden");
            });
            if (targetTab === "status-validation-tab") {
                document.getElementById("status-validation-config").classList.remove("hidden");
            } else if (targetTab === "order-validation-tab") {
                document.getElementById("order-validation-config").classList.remove("hidden");
            } else if (targetTab === "listing-qc-tab") {
                document.getElementById("listing-qc-config").classList.remove("hidden");
            }
        });
    });
}

// ================= EVENT LISTENERS =================
function initEventListeners() {
    // 1. Status Validation Country Dropdown: Show/Hide TikTok uploaders
    const statusCountrySelect = document.getElementById("status-country");
    const svTiktokUploaders = document.getElementById("sv-tiktok-uploaders");
    statusCountrySelect.addEventListener("change", () => {
        if (statusCountrySelect.value === "MY") {
            svTiktokUploaders.classList.remove("hidden");
        } else {
            svTiktokUploaders.classList.add("hidden");
        }
    });

    // 2. Order Validation: SLA Report Source selection toggle
    const slaSourceRadios = document.querySelectorAll("input[name='pending_source']");
    const orderPendingFileGroup = document.getElementById("order-pending-file-group");
    const gsheetUrlGroup = document.getElementById("gsheet-url-group");
    slaSourceRadios.forEach(radio => {
        radio.addEventListener("change", () => {
            if (radio.value === "Upload File") {
                orderPendingFileGroup.classList.remove("hidden");
                gsheetUrlGroup.classList.add("hidden");
            } else {
                orderPendingFileGroup.classList.add("hidden");
                gsheetUrlGroup.classList.remove("hidden");
            }
        });
    });

    // 3. SMTP configuration accordion
    const smtpToggle = document.getElementById("smtp-toggle");
    const smtpBodyArea = document.getElementById("smtp-body-area");
    smtpToggle.addEventListener("click", () => {
        smtpBodyArea.classList.toggle("hidden");
        smtpToggle.querySelector(".arrow").classList.toggle("active");
    });

    // 4. Listing QC Advanced parameters accordion
    const lqcAdvancedToggle = document.getElementById("lqc-advanced-toggle");
    const lqcAdvancedBody = document.getElementById("lqc-advanced-body");
    lqcAdvancedToggle.addEventListener("click", () => {
        lqcAdvancedBody.classList.toggle("hidden");
        lqcAdvancedToggle.querySelector(".arrow").classList.toggle("active");
    });

    // 5. Listing QC stage selection: Show/Hide Live Listing sync audit input
    const lqcStageSelect = document.getElementById("lqc-stage");
    const lqcPostQcFiles = document.getElementById("lqc-post-qc-files");
    const lqcSyncAuditSection = document.getElementById("lqc-sync-audit-section");
    lqcStageSelect.addEventListener("change", () => {
        if (lqcStageSelect.value === "Post QC") {
            lqcPostQcFiles.classList.remove("hidden");
            lqcSyncAuditSection.classList.remove("hidden");
        } else {
            lqcPostQcFiles.classList.add("hidden");
            lqcSyncAuditSection.classList.add("hidden");
        }
    });

    // ================= BUTTON API TRIGGERS =================
    
    // Status Validation: Run Validation
    document.getElementById("sv-run-validation-btn").addEventListener("click", runStatusValidation);
    
    // Status Validation: Run QC Audit
    document.getElementById("sv-run-qc-btn").addEventListener("click", runStatusQCAudit);
    
    // Order Validation: Run Validation
    document.getElementById("ov-run-btn").addEventListener("click", runOrderValidation);
    
    // Test SMTP credentials
    document.getElementById("smtp-test-btn").addEventListener("click", testSMTPConnection);
    
    // Listing QC: Run Validation
    document.getElementById("lqc-run-btn").addEventListener("click", runListingQC);

    // Listing QC Sync: Compare source against live store
    document.getElementById("lqc-run-sync-btn").addEventListener("click", runListingQCSyncCompare);

    // ================= DOWNLOAD BUTTON TRIGGERS =================
    document.getElementById("sv-download-report-btn").addEventListener("click", () => {
        if (currentReportBase64) downloadBase64File(currentReportBase64, currentReportName, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    });

    document.getElementById("sv-download-qc-btn").addEventListener("click", () => {
        if (currentQCBase64) downloadBase64File(currentQCBase64, currentQCName, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    });

    document.getElementById("ov-download-btn").addEventListener("click", () => {
        if (currentOrderReportBase64) downloadBase64File(currentOrderReportBase64, currentOrderReportName, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    });

    document.getElementById("lqc-download-btn").addEventListener("click", () => {
        if (currentLQCReportBase64) downloadBase64File(currentLQCReportBase64, currentLQCReportName, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    });

    document.getElementById("lqc-sync-download-btn").addEventListener("click", () => {
        if (currentLQCSyncBase64) downloadBase64File(currentLQCSyncBase64, currentLQCSyncName, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    });
}

// ================= API CALLBACK IMPLEMENTATIONS =================

// Base Fetch Function
async function sendAPIRequest(url, formData, onLoadingMsg = "Processing...") {
    try {
        const response = await fetch(API_BASE + url, {
            method: "POST",
            body: formData
        });
        if (!response.ok) {
            const errJson = await response.json().catch(() => ({}));
            throw new Error(errJson.error || errJson.message || `Server responded with ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error("API Error:", error);
        throw error;
    }
}

// Helper to download files in-browser from Base64
function downloadBase64File(base64Data, fileName, mimeType) {
    const byteCharacters = atob(base64Data);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray], {type: mimeType});
    
    const link = document.createElement("a");
    link.href = window.URL.createObjectURL(blob);
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// Task 1: Run Status Validation
async function runStatusValidation() {
    const initialInfo = document.getElementById("sv-initial-info");
    const loadingDiv = document.getElementById("sv-loading");
    const resultsDiv = document.getElementById("sv-metrics-results");
    const qcDiv = document.getElementById("sv-qc-results");

    initialInfo.classList.add("hidden");
    qcDiv.classList.add("hidden");
    resultsDiv.classList.add("hidden");
    loadingDiv.classList.remove("hidden");
    document.getElementById("sv-loading-msg").innerText = "Loading files and running SKU validations...";

    const fd = new FormData();
    fd.append("country", document.getElementById("status-country").value);
    
    // Add files
    const fileKeys = ["laz", "sh_stk", "sh_sts", "zal_stk", "zal_sts", "tt_act", "tt_ina", "cnt", "tc", "zec", "alf", "excl"];
    fileKeys.forEach(key => {
        const input = document.getElementById(`sv-${key.replace("_", "-")}`);
        if (input && input.files[0]) {
            fd.append(key, input.files[0]);
        }
    });

    try {
        const res = await sendAPIRequest("/api/status-validation", fd);
        
        // Hide loading
        loadingDiv.classList.add("hidden");
        resultsDiv.classList.remove("hidden");

        // Set metrics values
        document.getElementById("sv-val-total").innerText = res.metrics.total_rows;
        document.getElementById("sv-val-active").innerText = res.metrics.active_count;
        document.getElementById("sv-val-inactive").innerText = res.metrics.inactive_count;
        document.getElementById("sv-val-true").innerText = res.metrics.true_checks;

        // Store Excel base64
        currentReportBase64 = res.report_base64;
        currentReportName = res.report_name;

        // Render preview table
        const table = document.getElementById("sv-preview-table");
        table.innerHTML = "";
        if (res.preview && res.preview.length > 0) {
            // Header
            const headers = Object.keys(res.preview[0]);
            let headerHtml = "<tr>";
            headers.forEach(h => headerHtml += `<th>${h}</th>`);
            headerHtml += "</tr>";
            table.innerHTML += headerHtml;

            // Rows
            res.preview.forEach(row => {
                let rowHtml = "<tr>";
                headers.forEach(h => {
                    let val = row[h] !== null && row[h] !== undefined ? row[h] : "";
                    rowHtml += `<td>${val}</td>`;
                });
                rowHtml += "</tr>";
                table.innerHTML += rowHtml;
            });
        } else {
            table.innerHTML = "<tr><td>No data available in preview</td></tr>";
        }

    } catch (err) {
        loadingDiv.classList.add("hidden");
        initialInfo.classList.remove("hidden");
        alert(`Validation Failed: ${err.message}`);
    }
}

// Task 1: Run Status validation QC
async function runStatusQCAudit() {
    const initialInfo = document.getElementById("sv-initial-info");
    const loadingDiv = document.getElementById("sv-loading");
    const resultsDiv = document.getElementById("sv-metrics-results");
    const qcDiv = document.getElementById("sv-qc-results");

    const workingFileInput = document.getElementById("sv-working");
    if (!workingFileInput.files[0]) {
        alert("Please upload the Team Working Sheet (.xlsx) in the files section first to run QC.");
        return;
    }

    initialInfo.classList.add("hidden");
    resultsDiv.classList.add("hidden");
    qcDiv.classList.add("hidden");
    loadingDiv.classList.remove("hidden");
    document.getElementById("sv-loading-msg").innerText = "Executing cross-check validation audit...";

    const fd = new FormData();
    fd.append("country", document.getElementById("status-country").value);
    fd.append("qc_working_file", workingFileInput.files[0]);

    // Add remaining raw reference files
    const fileKeys = ["laz", "sh_stk", "sh_sts", "zal_stk", "zal_sts", "tt_act", "tt_ina", "cnt", "tc", "zec", "alf", "excl"];
    fileKeys.forEach(key => {
        const input = document.getElementById(`sv-${key.replace("_", "-")}`);
        if (input && input.files[0]) {
            fd.append(key, input.files[0]);
        }
    });

    try {
        const res = await sendAPIRequest("/api/status-validation-qc", fd);
        
        loadingDiv.classList.add("hidden");
        qcDiv.classList.remove("hidden");

        // Set metrics
        document.getElementById("sv-qc-total").innerText = res.metrics.total_rows_checked;
        document.getElementById("sv-qc-mismatch").innerText = res.metrics.mismatches_count;
        document.getElementById("sv-qc-missing").innerText = res.metrics.missing_rows_count;
        document.getElementById("sv-qc-extra").innerText = res.metrics.extra_rows_count;

        currentQCBase64 = res.report_base64;
        currentQCName = res.report_name;

        // Alerts box
        const alertArea = document.getElementById("qc-alert-area");
        alertArea.innerHTML = "";
        if (res.metrics.mismatches_count > 0) {
            alertArea.innerHTML = `
                <div class="alert-box error">
                    <i class="fa-solid fa-triangle-exclamation"></i>
                    <span>Found mismatches in validation results! Download the detailed QC Audit Excel report to verify differences.</span>
                </div>
            `;
        } else {
            alertArea.innerHTML = `
                <div class="alert-box success">
                    <i class="fa-solid fa-circle-check"></i>
                    <span>All checked SKUs match the working sheet perfectly!</span>
                </div>
            `;
        }

    } catch (err) {
        loadingDiv.classList.add("hidden");
        initialInfo.classList.remove("hidden");
        alert(`QC Validation Failed: ${err.message}`);
    }
}

// Task 2: Run Order pending SLA Validation
async function runOrderValidation() {
    const initialInfo = document.getElementById("ov-initial-info");
    const loadingDiv = document.getElementById("ov-loading");
    const resultsDiv = document.getElementById("ov-results-area");

    initialInfo.classList.add("hidden");
    resultsDiv.classList.add("hidden");
    loadingDiv.classList.remove("hidden");

    const fd = new FormData();
    const pendingSource = document.querySelector("input[name='pending_source']:checked").value;
    fd.append("pending_source", pendingSource);

    if (pendingSource === "Upload File") {
        const input = document.getElementById("ov-pending");
        if (input.files[0]) fd.append("order_pending", input.files[0]);
    } else {
        fd.append("gsheet_url", document.getElementById("order-gsheet-url").value);
    }

    fd.append("order_tc", document.getElementById("ov-tc").files[0]);
    fd.append("order_oms", document.getElementById("ov-oms").files[0]);
    
    const contactInput = document.getElementById("ov-contacts");
    if (contactInput.files[0]) fd.append("seller_contacts", contactInput.files[0]);

    try {
        const res = await sendAPIRequest("/api/order-validation", fd);
        
        loadingDiv.classList.add("hidden");
        resultsDiv.classList.remove("hidden");

        // Metrics
        document.getElementById("ov-total").innerText = res.metrics.total_pending_orders;
        document.getElementById("ov-pushed").innerText = res.metrics.pushed_count;
        document.getElementById("ov-notpushed").innerText = res.metrics.not_pushed_count;
        document.getElementById("ov-unpaid").innerText = res.metrics.unpaid_count;
        document.getElementById("ov-disc").innerText = res.metrics.total_discrepancies;

        currentOrderReportBase64 = res.report_base64;
        currentOrderReportName = res.report_name;
        currentSellerGroups = res.seller_groups;
        currentDiscrepanciesAll = res.discrepancies_all;

        // Discrepancy table preview
        const table = document.getElementById("ov-disc-table");
        table.innerHTML = "";
        if (res.discrepancies_preview && res.discrepancies_preview.length > 0) {
            const headers = Object.keys(res.discrepancies_preview[0]);
            let headerHtml = "<tr>";
            headers.forEach(h => headerHtml += `<th>${h}</th>`);
            headerHtml += "</tr>";
            table.innerHTML += headerHtml;

            res.discrepancies_preview.forEach(row => {
                let rowHtml = "<tr>";
                headers.forEach(h => {
                    let val = row[h] !== null && row[h] !== undefined ? row[h] : "";
                    rowHtml += `<td>${val}</td>`;
                });
                rowHtml += "</tr>";
                table.innerHTML += rowHtml;
            });
        } else {
            table.innerHTML = "<tr><td>No discrepancies found</td></tr>";
        }

        // Render seller email controls
        renderSellerList();

    } catch (err) {
        loadingDiv.classList.add("hidden");
        initialInfo.classList.remove("hidden");
        alert(`Order Validation Failed: ${err.message}`);
    }
}

// Render the list of sellers in Order Validation
function renderSellerList() {
    const listArea = document.getElementById("seller-list-area");
    listArea.innerHTML = "";

    if (!currentSellerGroups || Object.keys(currentSellerGroups).length === 0) {
        listArea.innerHTML = `<div class="empty-state">No seller data available.</div>`;
        return;
    }

    Object.keys(currentSellerGroups).forEach((sellerName, idx) => {
        const info = currentSellerGroups[sellerName];
        const row = document.createElement("div");
        row.className = "seller-item-row";
        row.innerHTML = `
            <div class="seller-name">${sellerName}</div>
            <div class="seller-count">Orders: ${info.data.length}</div>
            <div>
                <input type="email" class="seller-email-input" id="seller-email-${idx}" value="${info.email || ''}" placeholder="Enter Email">
            </div>
            <div>
                <button class="btn primary-btn seller-send-btn" onclick="sendSingleSellerEmail('${sellerName}', ${idx})">
                    <i class="fa-solid fa-paper-plane"></i> Send
                </button>
            </div>
        `;
        listArea.appendChild(row);
    });

    // Set up click listener for Email All button
    document.getElementById("email-all-btn").onclick = sendAllSellerEmails;
}

// Get client-side SMTP config object
function getSMTPConfig() {
    return {
        host: document.getElementById("smtp-host").value,
        port: parseInt(document.getElementById("smtp-port").value) || 587,
        user: document.getElementById("smtp-user").value,
        password: document.getElementById("smtp-pass").value,
        sender_email: document.getElementById("smtp-sender").value,
        use_tls: document.getElementById("smtp-tls").checked
    };
}

// Check SMTP configurations are filled
function validateSMTPConfig(cfg) {
    if (!cfg.host || !cfg.user || !cfg.password) {
        alert("Please expand and fill SMTP Mail Server Settings (Host, Email, Password) to send emails.");
        return false;
    }
    return true;
}

// Test SMTP connection
async function testSMTPConnection() {
    const cfg = getSMTPConfig();
    if (!validateSMTPConfig(cfg)) return;

    const testBtn = document.getElementById("smtp-test-btn");
    testBtn.innerText = "Testing Connection...";
    testBtn.disabled = true;

    try {
        const response = await fetch(API_BASE + "/api/test-smtp", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(cfg)
        });
        const res = await response.json();
        alert(res.message);
    } catch (err) {
        alert(`SMTP Connection Failed: ${err.message}`);
    } finally {
        testBtn.innerText = "Test Connection";
        testBtn.disabled = false;
    }
}

// Send email to a single seller
async function sendSingleSellerEmail(sellerName, idx) {
    const cfg = getSMTPConfig();
    if (!validateSMTPConfig(cfg)) return;

    const emailInput = document.getElementById(`seller-email-${idx}`);
    const recipient = emailInput.value.trim();
    if (!recipient || !recipient.includes("@")) {
        alert("Please enter a valid recipient email address.");
        return;
    }

    const info = currentSellerGroups[sellerName];
    const sendBtn = emailInput.parentElement.parentElement.querySelector(".seller-send-btn");
    const originalText = sendBtn.innerHTML;
    sendBtn.innerHTML = "<i class='fa-solid fa-spinner fa-spin'></i>";
    sendBtn.disabled = true;

    try {
        const response = await fetch(API_BASE + "/api/send-email", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                smtp_config: cfg,
                seller_name: sellerName,
                recipient_email: recipient,
                seller_data: info.data,
                discrepancies_data: currentDiscrepanciesAll
            })
        });
        const res = await response.json();
        alert(res.message);
    } catch (err) {
        alert(`Failed to send email to ${sellerName}: ${err.message}`);
    } finally {
        sendBtn.innerHTML = originalText;
        sendBtn.disabled = false;
    }
}

// Send emails to all sellers
async function sendAllSellerEmails() {
    const cfg = getSMTPConfig();
    if (!validateSMTPConfig(cfg)) return;

    const emailAllBtn = document.getElementById("email-all-btn");
    emailAllBtn.innerHTML = "<i class='fa-solid fa-spinner fa-spin'></i> Sending to all...";
    emailAllBtn.disabled = true;

    let successCount = 0;
    let failCount = 0;

    const sellers = Object.keys(currentSellerGroups);
    for (let idx = 0; idx < sellers.length; idx++) {
        const sellerName = sellers[idx];
        const emailInput = document.getElementById(`seller-email-${idx}`);
        const recipient = emailInput.value.trim();

        if (!recipient || !recipient.includes("@")) {
            console.warn(`Skipped ${sellerName} due to invalid email address.`);
            failCount++;
            continue;
        }

        const info = currentSellerGroups[sellerName];

        try {
            const response = await fetch(API_BASE + "/api/send-email", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    smtp_config: cfg,
                    seller_name: sellerName,
                    recipient_email: recipient,
                    seller_data: info.data,
                    discrepancies_data: currentDiscrepanciesAll
                })
            });
            const res = await response.json();
            if (res.success) {
                successCount++;
            } else {
                console.error(`SMTP error for ${sellerName}:`, res.message);
                failCount++;
            }
        } catch (err) {
            console.error(`Network error for ${sellerName}:`, err);
            failCount++;
        }
    }

    alert(`Finished sending reports!\nSuccessfully sent: ${successCount}\nFailed/Skipped: ${failCount}`);
    emailAllBtn.innerHTML = "<i class='fa-solid fa-paper-plane'></i> Email All Sellers";
    emailAllBtn.disabled = false;
}

// Task 3: Run Listing QC Validation
async function runListingQC() {
    const initialInfo = document.getElementById("lqc-initial-info");
    const loadingDiv = document.getElementById("lqc-loading");
    const resultsDiv = document.getElementById("lqc-results-area");

    initialInfo.classList.add("hidden");
    resultsDiv.classList.add("hidden");
    loadingDiv.classList.remove("hidden");

    // Hide comparison section reset
    document.getElementById("lqc-sync-results").classList.add("hidden");

    const fd = new FormData();
    fd.append("channel", document.getElementById("lqc-channel").value);
    fd.append("qc_stage", document.getElementById("lqc-stage").value);
    fd.append("check_live_images", document.getElementById("lqc-images-check").checked);
    fd.append("allowed_genders", document.getElementById("lqc-genders").value);
    fd.append("allowed_statuses", document.getElementById("lqc-statuses").value);

    // Add references
    const refContent = document.getElementById("lqc-ref-content").files[0];
    const refZecom = document.getElementById("lqc-ref-zecom").files[0];
    if (refContent) fd.append("content", refContent);
    if (refZecom) fd.append("zecom", refZecom);

    // Target sheets multiple
    const targetInput = document.getElementById("lqc-targets");
    if (targetInput.files.length > 0) {
        for (let i = 0; i < targetInput.files.length; i++) {
            fd.append(`target_${i}`, targetInput.files[i]);
        }
    }

    // Pass Gsheet URL link inputs (we could implement sheet fetching, but it's simpler to ask users to copy Excel file as backend doesn't support Google OAuth callbacks for serverless API)
    fd.append("gsheet_urls", document.getElementById("lqc-gsheets").value);

    try {
        const res = await sendAPIRequest("/api/listing-qc", fd);
        
        loadingDiv.classList.add("hidden");
        resultsDiv.classList.remove("hidden");

        // KPI Metrics
        document.getElementById("lqc-total").innerText = res.metrics.total_records;
        document.getElementById("lqc-skus").innerText = res.metrics.total_skus;
        document.getElementById("lqc-articles").innerText = res.metrics.total_articles;
        document.getElementById("lqc-exceptions").innerText = res.metrics.total_exceptions;

        currentLQCReportBase64 = res.report_base64;
        currentLQCReportName = res.report_name;
        currentLQCValDf = res.val_df_json; // Save standard output data in memory for sync audit comparison

        // Compliance Checklist badges
        setQCChecklistBadge("qc-chk-zecom-text", "qc-chk-zecom-res", res.checklist.zecom_status_mismatches === 0, `${res.checklist.zecom_status_mismatches} mismatches`);
        setQCChecklistBadge("qc-chk-launch-text", "qc-chk-launch-res", res.checklist.future_launch_dates === 0, `${res.checklist.future_launch_dates} future launch dates`);
        setQCChecklistBadge("qc-chk-gender-text", "qc-chk-gender-res", res.checklist.gender_mismatches === 0, `${res.checklist.gender_mismatches} mismatches`);
        setQCChecklistBadge("qc-chk-color-text", "qc-chk-color-res", res.checklist.color_mismatches === 0, `${res.checklist.color_mismatches} mismatches`);
        setQCChecklistBadge("qc-chk-size-text", "qc-chk-size-res", res.checklist.size_mismatches === 0, `${res.checklist.size_mismatches} mismatches`);
        setQCChecklistBadge("qc-chk-price-text", "qc-chk-price-res", res.checklist.price_mismatches === 0, `${res.checklist.price_mismatches} mismatches`);
        setQCChecklistBadge("qc-chk-qty-text", "qc-chk-qty-res", res.checklist.nonzero_quantities === 0, `${res.checklist.nonzero_quantities} non-zero items`);

    } catch (err) {
        loadingDiv.classList.add("hidden");
        initialInfo.classList.remove("hidden");
        alert(`Listing QC Failed: ${err.message}`);
    }
}

// Helper to set color badges in QC checklist table
function setQCChecklistBadge(textId, resId, isOk, errorMsg) {
    const textTd = document.getElementById(textId);
    const resTd = document.getElementById(resId);

    if (isOk) {
        textTd.innerText = "All items compatible";
        resTd.innerHTML = `<span class="qc-badge ok">OK</span>`;
    } else {
        textTd.innerText = errorMsg;
        resTd.innerHTML = `<span class="qc-badge err">Mismatch</span>`;
    }
}

// Task 3: Compare source against live store indices (Post QC stage only)
async function runListingQCSyncCompare() {
    const syncLoading = document.getElementById("lqc-sync-loading");
    const syncResults = document.getElementById("lqc-sync-results");

    const liveReportsInput = document.getElementById("lqc-live-reports");
    if (liveReportsInput.files.length === 0) {
        alert("Please upload at least one Live Store Marketplace Report in the configuration form first.");
        return;
    }

    if (!currentLQCValDf) {
        alert("Please run target Listing QC Validation first before running Comparison Audit.");
        return;
    }

    syncResults.classList.add("hidden");
    syncLoading.classList.remove("hidden");

    const fd = new FormData();
    fd.append("channel", document.getElementById("lqc-channel").value);
    
    // Add live files
    for (let i = 0; i < liveReportsInput.files.length; i++) {
        fd.append(`live_${i}`, liveReportsInput.files[i]);
    }

    try {
        // Send AJAX request with files in formData, and val_df inside JSON request
        const response = await fetch(API_BASE + "/api/listing-qc-compare", {
            method: "POST",
            body: fd
        });
        
        // Wait, how do we send BOTH files (FormData) AND json data (val_df)?
        // We can append val_df stringified into the FormData!
        // Let's modify:
        const fdExtended = new FormData();
        fdExtended.append("channel", document.getElementById("lqc-channel").value);
        for (let i = 0; i < liveReportsInput.files.length; i++) {
            fdExtended.append(`live_${i}`, liveReportsInput.files[i]);
        }
        
        // Build JSON structure for payload and send it in a separate call, OR put val_df into FormData as a text field and parse it on Python!
        // Let's pass it in FormData as a text field string:
        fdExtended.append("val_df_string", JSON.stringify(currentLQCValDf));

        // Re-send extended FormData
        const responseExtended = await fetch(API_BASE + "/api/listing-qc-compare", {
            method: "POST",
            body: fdExtended
        });

        if (!responseExtended.ok) {
            const errJson = await responseExtended.json().catch(() => ({}));
            throw new Error(errJson.error || errJson.message || "Failed to compare live database.");
        }
        const res = await responseExtended.json();

        syncLoading.classList.add("hidden");
        syncResults.classList.remove("hidden");

        // KPI metrics
        document.getElementById("lqc-sync-passed").innerText = res.metrics["Passed Matching"] || 0;
        document.getElementById("lqc-sync-price-err").innerText = res.metrics["Price Mismatches"] || 0;
        document.getElementById("lqc-sync-status-err").innerText = res.metrics["Status Mismatches"] || 0;
        document.getElementById("lqc-sync-stock-err").innerText = res.metrics["Stock Mismatches"] || 0;

        currentLQCSyncBase64 = res.report_base64;
        currentLQCSyncName = res.report_name;

        // Render sync mismatch list
        const table = document.getElementById("lqc-sync-mismatch-table");
        table.innerHTML = "";
        if (res.mismatches && res.mismatches.length > 0) {
            const headers = Object.keys(res.mismatches[0]);
            let headerHtml = "<tr>";
            headers.forEach(h => headerHtml += `<th>${h}</th>`);
            headerHtml += "</tr>";
            table.innerHTML += headerHtml;

            res.mismatches.forEach(row => {
                let rowHtml = "<tr>";
                headers.forEach(h => {
                    let val = row[h] !== null && row[h] !== undefined ? row[h] : "";
                    rowHtml += `<td>${val}</td>`;
                });
                rowHtml += "</tr>";
                table.innerHTML += rowHtml;
            });
        } else {
            table.innerHTML = "<tr><td>All variants are completely in sync!</td></tr>";
        }

    } catch (err) {
        syncLoading.classList.add("hidden");
        alert(`Sync Comparison Failed: ${err.message}`);
    }
}
