import os
import subprocess

import pytest

from app import db


def _test_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


@pytest.fixture(scope="session")
def test_url() -> str:
    url = _test_url()
    with db.connect(url) as conn:  # fresh schema each test session
        # drop tables only: extensions (vector, pg_trgm) need superuser to recreate
        conn.execute(
            "DO $$ DECLARE r record; BEGIN "
            "FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP "
            "EXECUTE 'DROP TABLE IF EXISTS public.' || quote_ident(r.tablename) || ' CASCADE'; "
            "END LOOP; END $$;"
        )
    return url


@pytest.fixture()
def conn(test_url):
    db.migrate(test_url)
    with db.connect(test_url) as c:
        yield c
