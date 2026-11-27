"""Identify the language of the specification prose, excluding its code examples."""

import re


MARKUP = re.compile(r"```[\s\S]*?(?:```|\Z)|`[^`\n]*`|https?://\S+|\b[A-ZА-ЯЁ]{1,8}-\d+(?:\.\d+)*\b")


def detect_source_language(text):
    from py3langid import classify

    prose = " ".join(re.findall(r"[^\W\d_]+", MARKUP.sub(" ", text)))
    if sum(c.isalpha() for c in prose) < 8:
        return "und"
    # Retain context from the beginning, middle and end of a long specification.
    if len(prose) > 12000:
        mid = len(prose) // 2
        prose = " ".join((prose[:4000], prose[mid - 2000:mid + 2000], prose[-4000:]))
    return classify(prose)[0]
