"""Shared pytest fixtures for the postbot test suite."""

from __future__ import annotations

from pathlib import Path

import pytest
import toml

from mmbot_framework import ParsedMessage


# ---------------------------------------------------------------------------
# Minimal config kwargs
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_config_kwargs() -> dict:
    """Return the minimum required fields for constructing a PostBotConfig."""
    return {
        "url": "mm.example.com",
        "token": "test-token",
        "team_name": "myteam",
    }


# ---------------------------------------------------------------------------
# channels.toml fixture file
# ---------------------------------------------------------------------------


_CHANNELS_TOML_CONTENT = {
    "whitelist": {
        "ch-id-1": {"id": "ch_id_1", "aliases": []},
        "ch-id-2": {"id": "ch_id_2", "aliases": []},
        "ch-id-3": {"id": "ch_id_3", "aliases": []},
        "whitelisted": {"id": "whitelisted_id", "aliases": []},
    },
    "groups": {
        "TestGroup": {"channels": ["ch_id_1", "ch_id_2"], "aliases": ["tg"]},
    },
    "private_groups": {
        "PrivateGroup": {"channels": ["ch_id_3"], "aliases": []},
    },
}


@pytest.fixture
def channels_file(tmp_path: Path) -> Path:
    """Write a channels.toml into tmp_path and return the Path."""
    p = tmp_path / "channels.toml"
    p.write_text(toml.dumps(_CHANNELS_TOML_CONTENT))
    return p


# ---------------------------------------------------------------------------
# ParsedMessage factory
# ---------------------------------------------------------------------------


def _make_msg(
    *,
    sender_id: str = "user_id_1",
    sender_name: str = "@testuser",
    channel_id: str = "dm_channel_id_1",
    channel_type: str = "D",
    text: str = "",
    file_ids: list[str] | None = None,
    raw: dict | None = None,
) -> ParsedMessage:
    """Create a :class:`ParsedMessage` with sensible defaults."""
    return ParsedMessage(
        sender_id=sender_id,
        sender_name=sender_name,
        channel_id=channel_id,
        channel_type=channel_type,
        text=text,
        file_ids=file_ids if file_ids is not None else [],
        raw=raw if raw is not None else {},
    )


@pytest.fixture
def make_msg():
    """Return the ``_make_msg`` factory function."""
    return _make_msg
