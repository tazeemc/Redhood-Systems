"""Tests for accounts_db against a temporary database (never redhood.db)."""

import pytest

import accounts_db


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point accounts_db at a throwaway SQLite file."""
    path = str(tmp_path / 'test.db')
    monkeypatch.setattr(accounts_db, 'DB_PATH', path)
    accounts_db.init_db()
    return path


def test_init_seeds_default_accounts(tmp_db):
    handles = accounts_db.get_active_handles()
    assert handles == [h for h, _, _ in accounts_db.DEFAULT_ACCOUNTS]


def test_init_is_idempotent(tmp_db):
    accounts_db.init_db()
    accounts_db.init_db()
    assert len(accounts_db.get_active_handles()) == len(accounts_db.DEFAULT_ACCOUNTS)


def test_add_account_strips_at_prefix(tmp_db):
    accounts_db.add_account('@newhandle', category='test')
    assert 'newhandle' in accounts_db.get_active_handles()


def test_add_duplicate_does_not_raise(tmp_db):
    accounts_db.add_account('dupe')
    accounts_db.add_account('dupe')  # IntegrityError swallowed
    assert accounts_db.get_active_handles().count('dupe') == 1


def test_toggle_deactivates_and_reactivates(tmp_db):
    handle = accounts_db.DEFAULT_ACCOUNTS[0][0]
    accounts_db.toggle_account(handle)
    assert handle not in accounts_db.get_active_handles()
    accounts_db.toggle_account(handle)
    assert handle in accounts_db.get_active_handles()


def test_remove_account(tmp_db):
    accounts_db.add_account('doomed')
    accounts_db.remove_account('doomed')
    assert 'doomed' not in accounts_db.get_active_handles()
