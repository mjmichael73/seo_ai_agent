const form = document.querySelector("#audit-form");
const statusNode = document.querySelector("#status");
const resultsNode = document.querySelector("#results");
const submitButton = document.querySelector("#submit");

function textElement(tag, text, className = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  return element;
}

function renderReport(report) {
  resultsNode.replaceChildren();
  resultsNode.append(textElement("h2", "Audit overview"));

  const head = document.createElement("div");
  head.className = "report-head";
  head.append(textElement("div", `${report.score}`, "score"));
  const summary = textElement("p", report.summary, "report-summary");
  head.append(summary);
  resultsNode.append(head);
  resultsNode.append(textElement("p", `${report.pages.length} page(s) inspected · ${report.findings.length} finding(s)`, "hint"));

  if (report.priority_actions.length) {
    resultsNode.append(textElement("h2", "Start here"));
    report.priority_actions.forEach((action) => resultsNode.append(textElement("p", action, "report-summary")));
  }
  if (!report.findings.length) {
    resultsNode.append(textElement("p", "No rule-based findings were raised for the inspected pages.", "status"));
  }
  report.findings.forEach((finding) => {
    const card = document.createElement("article");
    card.className = "finding";
    const title = document.createElement("div");
    title.className = "finding-title";
    title.append(textElement("span", finding.severity, `badge ${finding.severity}`));
    title.append(textElement("span", finding.issue));
    card.append(title);
    card.append(textElement("p", `${finding.evidence} Recommendation: ${finding.recommendation}`));
    resultsNode.append(card);
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  statusNode.textContent = "Auditing public pages…";
  statusNode.className = "status";
  submitButton.disabled = true;
  const payload = {
    url: document.querySelector("#url").value,
    max_pages: Number(document.querySelector("#max-pages").value),
    keyword: document.querySelector("#keyword").value.trim() || null,
  };
  try {
    const response = await fetch("/api/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "The audit could not be completed.");
    renderReport(data);
    statusNode.textContent = "Audit complete. Review each recommendation before making changes.";
  } catch (error) {
    statusNode.textContent = error.message || "The audit failed. Please try again.";
    statusNode.className = "status error";
  } finally {
    submitButton.disabled = false;
  }
});
