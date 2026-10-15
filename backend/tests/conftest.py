import os

import pytest

from app import db

_RESET_SQL = (
    "DO $$ DECLARE r record; BEGIN "
    "FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP "
    "EXECUTE 'DROP TABLE IF EXISTS public.' || quote_ident(r.tablename) || ' CASCADE'; "
    "END LOOP; END $$;"
)


def reset_db(url: str) -> None:
    """Drop tables only: extensions (vector, pg_trgm) need superuser to recreate."""
    with db.connect(url) as c:
        c.execute(_RESET_SQL)


@pytest.fixture(scope="session")
def test_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


@pytest.fixture()
def conn(test_url):
    """Fresh, fully migrated database for every test (isolation > speed at this size)."""
    reset_db(test_url)
    db.migrate(test_url)
    with db.connect(test_url) as c:
        yield c
