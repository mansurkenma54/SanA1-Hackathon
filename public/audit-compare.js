function normalized(text) {
  return text.normalize().trim().replace(/\s+/gu, " ");
}

function indexFindings(findings) {
  const index = new Map();
  for (const finding of findings) {
    const evidence = finding.evidence.map(({ quote, section, source_id: sourceId }) =>
      JSON.stringify([normalized(quote), normalized(section || ""), normalized(sourceId || "")]));
    const key = JSON.stringify([finding.criterion, normalized(finding.question), [...new Set(evidence)].sort()]);
    const items = index.get(key) || [];
    items.push(finding);
    index.set(key, items);
  }
  return index;
}

export function compareAudits(before, after) {
  const initial = indexFindings(before.findings);
  const updated = indexFindings(after.findings);
  const matches = new Map();
  const matchedAfter = new Set();
  for (const [key, entries] of initial) {
    const candidates = updated.get(key);
    if (entries.length === 1 && candidates?.length === 1) {
      matches.set(entries[0].id, candidates[0].id);
      matchedAfter.add(candidates[0].id);
    }
  }
  return {
    before_sha256: before.sha256,
    after_sha256: after.sha256,
    repeated: [...matches].map(([before_id, after_id]) => ({ before_id, after_id })),
    needs_review: before.findings.filter(item => !matches.has(item.id)),
    unmatched_after: after.findings.filter(item => !matchedAfter.has(item.id)).map(item => item.id),
  };
}
