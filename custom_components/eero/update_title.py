"""The firmware title an update entity shows.

Kept free of Home Assistant and package imports so it can be tested on its
own (the fork's tests run without Home Assistant installed).

eero reports the target firmware's title with its version on the end
("eeroOS 7.17.2"), and Home Assistant's Settings > Updates list prints the
title followed by the latest version, so the version showed twice
("eeroOS 7.17.2 v7.17.2"). Upstream PR #176 proposed dropping the title's
last word, which would also clip a title that carries no version; this only
drops a trailing version that matches the latest version (with or without a
leading "v") and leaves every other title as eero sent it.
"""

from __future__ import annotations


def firmware_title(title: str | None, latest_version: str | None) -> str | None:
    """Return the title without a trailing copy of the latest version."""
    if not title or not latest_version:
        return title
    version = latest_version.strip()
    bare = version[1:] if version[:1] in ("v", "V") else version
    if not bare:
        return title
    head, sep, tail = title.rstrip().rpartition(" ")
    if sep and head.strip() and tail in (bare, "v" + bare, "V" + bare):
        return head.rstrip()
    return title
