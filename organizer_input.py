"""Load the published competition input at the revision used for verification."""

from functools import cache
from hashlib import sha256
from urllib.request import urlopen


ORGANIZER_REVISION = "928c1aa364265426105b69ba7a3444eac11b22db"
OFFICIAL_SHA256 = "e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381"
SOURCE_URL = ("https://raw.githubusercontent.com/BCC-HUB/ai-requirements-validator-task/"
              f"{ORGANIZER_REVISION}/docs/requirements.md")


@cache
def official_input_bytes():
    with urlopen(SOURCE_URL, timeout=6) as response:
        data = response.read(256 * 1024 + 1)
    if sha256(data).hexdigest() != OFFICIAL_SHA256:
        raise ValueError("official_input_unavailable")
    return data
