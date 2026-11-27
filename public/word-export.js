import { wordImageReferences } from "./document-view.js";

export async function downloadWord(text, media, locale) {
  const response = await fetch("/api/export/docx", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: wordImageReferences(text, media), media, locale }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || "generic");
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = locale === "ru" ? "SanA1-ТЗ.docx" : "SanA1-specification.docx";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
