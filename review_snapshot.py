"""Authenticated, short-lived browser snapshots for unchanged clause reviews."""

from hashlib import sha256
import json
import os

from itsdangerous import BadData, URLSafeTimedSerializer


MAX_TOKEN = 320_000


def block_fingerprints(blocks):
    fingerprints = {}
    for index, block in enumerate(blocks):
        context = [other.as_prompt_data() for other in blocks[max(0, index - 1):index + 2]]
        for item in context:
            item.pop("ref")
        serialized = json.dumps([min(index, 1), context], ensure_ascii=False, separators=(",", ":"))
        fingerprints[block.ref] = sha256(serialized.encode()).hexdigest()
    return fingerprints


def serializer():
    key = (os.getenv("SANA1_RECHECK_SECRET") or os.getenv("GEMINI_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()
    if not key:
        return None
    secret = sha256(b"SanA1 recheck snapshot\0" + key.encode()).digest()
    return URLSafeTimedSerializer(secret, salt="san-a1-clause-review-v1")


def read_snapshot(token, version):
    signer = serializer()
    if signer is None or not isinstance(token, str) or not token or len(token) > MAX_TOKEN:
        return {}
    try:
        snapshot = signer.loads(token, max_age=6 * 3600)
    except BadData:
        return {}
    return snapshot.get("entries", {}) if isinstance(snapshot, dict) and snapshot.get("version") == version else {}


def sign_snapshot(entries, version):
    signer = serializer()
    if signer is None or not entries:
        return None
    token = signer.dumps({"version": version, "entries": entries})
    return token if len(token) <= MAX_TOKEN else None
