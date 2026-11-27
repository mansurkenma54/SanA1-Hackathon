const key = "sana1-workspace-v1";
const maxLength = 2_000_000;

export function readWorkspaceSession(storage) {
  try {
    const raw = storage.getItem(key);
    if (!raw || raw.length > maxLength) return null;
    const saved = JSON.parse(raw);
    return saved?.version === 1 && typeof saved.text === "string" ? saved : null;
  } catch {
    return null;
  }
}

export function writeWorkspaceSession(storage, snapshot) {
  for (const [value, status] of [[snapshot, "sessionSaved"],
    [{ ...snapshot, media: [] }, "sessionTextOnly"],
    [{ text: snapshot.text, file: snapshot.file, pdfOrigin: snapshot.pdfOrigin }, "sessionDraftOnly"]]) {
    const raw = JSON.stringify({ version: 1, ...value });
    if (raw.length > maxLength) continue;
    try {
      storage.setItem(key, raw);
      return status;
    } catch (error) {
      if (error.name !== "QuotaExceededError") break;
    }
  }
  clearWorkspaceSession(storage);
  return "sessionUnavailable";
}

export function clearWorkspaceSession(storage) {
  try { storage.removeItem(key); }
  catch { /* Storage may be disabled. */ }
}

export function recoverableAudit(audit) {
  const source = value => typeof value?.quote === "string" && typeof value.location === "string" &&
    Number.isInteger(value.line) && Number.isInteger(value.end) &&
    (value.section == null || typeof value.section === "string") &&
    (value.source_id == null || typeof value.source_id === "string");
  const evidence = value => Array.isArray(value) && value.every(source);
  return Boolean(audit?.schema_version === 1 && ["rules", "gemini"].includes(audit.mode) &&
    typeof audit.sha256 === "string" && typeof audit.verdict === "string" &&
    Array.isArray(audit.findings) && audit.findings.every(item => typeof item?.id === "string" &&
      typeof item.question === "string" && typeof item.criterion === "string" && evidence(item.evidence) &&
      Array.isArray(item.requirements)) &&
    Array.isArray(audit.requirements) && audit.requirements.every(item => typeof item?.id === "string" &&
      typeof item.summary === "string" && source(item.source) && Array.isArray(item.findings)) &&
    Array.isArray(audit.checks) && audit.checks.every(item => evidence(item?.evidence)) &&
    Array.isArray(audit.passes) && Array.isArray(audit.warnings) &&
    audit.counts && ["blocked", "clarify", "limited", "ready"].includes(audit.readiness));
}
