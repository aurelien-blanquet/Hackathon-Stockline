"""Shared test setup."""

import pytest

from app.market import levers


@pytest.fixture(autouse=True)
def fresh_lever_memory(monkeypatch):
    """Every test starts with an empty, in-memory lever memory (market/levers.py): no file written, no learning
    carried from one test to the next."""
    monkeypatch.setattr(levers, "MEMORY", levers.LeverMemory())
