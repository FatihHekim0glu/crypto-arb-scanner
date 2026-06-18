"""Lazy loader for the bundled reference cost profiles.

The reference fee/transfer schedules ship as ``profiles/*.yaml`` inside the
package. This module locates and parses one profile on demand, importing
``pyyaml`` lazily so that importing the :mod:`cryptoarb.costs` package has no
side effects and pulls in no optional dependency at import time.

Importing this module has no side effects.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib import resources
from typing import Any

from cryptoarb._exceptions import ValidationError

# The three reference profiles bundled with the package.
KNOWN_PROFILES: tuple[str, ...] = ("default", "low", "high")

# Profiles live in the top-level package, not in costs/ - they are shared with
# any other consumer (CLI, backend) that needs the raw reference numbers.
_PROFILE_PACKAGE = "cryptoarb.profiles"


def load_profile(profile: str) -> dict[str, Any]:
    """Read and parse one bundled cost profile into a plain ``dict``.

    Parameters
    ----------
    profile:
        Profile name: ``"default"``, ``"low"``, or ``"high"``.

    Returns
    -------
    dict[str, Any]
        The parsed YAML document (with ``fees`` and ``transfers`` sections).

    Raises
    ------
    ValidationError
        If ``profile`` is unknown, the file is missing, or the parsed document
        is not a mapping.
    """
    if profile not in KNOWN_PROFILES:
        raise ValidationError(
            f"unknown cost profile {profile!r}; expected one of {KNOWN_PROFILES}."
        )

    # Lazy import: keeps `import cryptoarb.costs` free of the optional pyyaml dep.
    import yaml

    resource = resources.files(_PROFILE_PACKAGE).joinpath(f"{profile}.yaml")
    try:
        text = resource.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:  # pragma: no cover - packaging guard
        raise ValidationError(f"cost profile {profile!r} could not be read: {exc}.") from exc

    parsed: object = yaml.safe_load(text)
    if not isinstance(parsed, Mapping):
        raise ValidationError(f"cost profile {profile!r} did not parse to a mapping.")
    return dict(parsed)
