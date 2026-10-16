"""Create the test account that opens the demo organizations: python -m app.seed_users
Credentials are fixed and public on purpose (test data only): see README. Idempotent."""
from . import auth
from .db import connect, migrate

TEST_EMAIL, TEST_PASSWORD, TEST_NAME = "demo@gitwhy.test", "gitwhy-demo-2026", "Demo user"
TEST_ORGS = ("northwind", "oss-pallets")


def run() -> dict:
    migrate()
    with connect() as c:
        row = c.execute("SELECT id FROM users WHERE email=%s", (TEST_EMAIL,)).fetchone()
        uid = row["id"] if row else c.execute("INSERT INTO users (email, name, password_hash) VALUES (%s,%s,%s) RETURNING id",
                                              (TEST_EMAIL, TEST_NAME, auth.hash_password(TEST_PASSWORD))).fetchone()["id"]
        if row:
            c.execute("UPDATE users SET password_hash=%s WHERE id=%s", (auth.hash_password(TEST_PASSWORD), uid))
        joined = []
        for slug in TEST_ORGS:
            o = c.execute("SELECT id FROM organizations WHERE slug=%s", (slug,)).fetchone()
            if o:
                c.execute("INSERT INTO org_members (user_id, organization_id, role) VALUES (%s,%s,'member') ON CONFLICT DO NOTHING", (uid, o["id"]))
                c.execute("UPDATE organizations SET status='ready' WHERE id=%s", (o["id"],))
                joined.append(slug)
    return {"email": TEST_EMAIL, "organizations": joined}


if __name__ == "__main__":
    print(run())
