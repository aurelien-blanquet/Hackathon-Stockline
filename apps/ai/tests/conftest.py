"""Shared test setup."""

import pytest

from app.market import levers


@pytest.fixture(autouse=True)
def fresh_lever_memory(monkeypatch):
    """Every test starts with an empty, in-memory lever memory (market/levers.py): no file written, no learning
    carried from one test to the next."""
    monkeypatch.setattr(levers, "MEMORY", levers.LeverMemory())


@pytest.fixture(autouse=True)
def no_open_group_purchase():
    """Group purchases (market/pool.py) start empty in every test: no provisional order carried from another test."""
    from app.market import pool

    pool.GROUPS.clear()
    pool.DONE.clear()
    yield
    pool.GROUPS.clear()
