import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from dojo.adapters.db import Base
from sqlalchemy import create_engine, inspect, text


@pytest.fixture
def database(_pg_session):
    name = "init_" + uuid4().hex
    admin = _pg_session._engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = _pg_session._engine.url.set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    yield url, engine
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))


def config(url):
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def legacy(engine):
    """An unversioned database as 0013 create_all left it: no 0014 indexes."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS uq_jobs_active_render"))
        conn.execute(text("DROP INDEX IF EXISTS uq_yayin_zamani_regular_due"))
        conn.execute(text("ALTER TABLE jobs DROP COLUMN failure_generation"))
        conn.execute(text("DROP TABLE operational_deliveries"))
        conn.execute(text("DROP TABLE operational_alerts"))
        conn.execute(text("DROP TABLE monitoring_incidents"))


def assert_head(engine):
    with engine.connect() as conn:
        version = conn.scalar(text("SELECT version_num FROM alembic_version"))
        assert version == "0015_operational_monitoring"
    for table, expected in [
        ("jobs", "uq_jobs_active_render"), ("yayin_zamani", "uq_yayin_zamani_regular_due"),
    ]:
        indexes = inspect(engine).get_indexes(table)
        assert any(i["name"] == expected and i["unique"] for i in indexes)
    assert {"monitoring_incidents", "operational_alerts",
            "operational_deliveries"} <= set(inspect(engine).get_table_names())


def _shape(engine, table):
    inspector = inspect(engine)
    return {
        "columns": sorted(
            (c["name"], str(c["type"]), c["nullable"], c.get("default"))
            for c in inspector.get_columns(table)
        ),
        "pk": sorted(inspector.get_pk_constraint(table)["constrained_columns"]),
        "fk": sorted(
            (tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
            for fk in inspector.get_foreign_keys(table)
        ),
        "unique": sorted(
            tuple(u["column_names"]) for u in inspector.get_unique_constraints(table)
        ),
        "indexes": sorted(
            (i["name"], tuple(i["column_names"]), i["unique"]) for i in inspector.get_indexes(table)
        ),
    }


def test_migration_and_create_all_agree_on_new_objects(database, _pg_session):
    """The versioned migration must reproduce create_all, not merely run."""
    from dojo.schema import initialize_database

    url, engine = database
    initialize_database(url)
    fresh_name = "createall_" + uuid4().hex
    admin = _pg_session._engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{fresh_name}"'))
    fresh_url = _pg_session._engine.url.set(
        database=fresh_name
    ).render_as_string(hide_password=False)
    fresh_engine = create_engine(fresh_url)
    try:
        Base.metadata.create_all(fresh_engine)
        for table in ("monitoring_incidents", "operational_alerts", "operational_deliveries"):
            assert _shape(engine, table) == _shape(fresh_engine, table)
        # jobs: the new column only; 0001's own id/serial types differ by design.
        columns = {name: rest for name, *rest in _shape(engine, "jobs")["columns"]}
        fresh_columns = {name: rest for name, *rest in _shape(fresh_engine, "jobs")["columns"]}
        assert columns["failure_generation"] == fresh_columns["failure_generation"] == \
            ["INTEGER", False, "0"]
    finally:
        fresh_engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{fresh_name}" WITH (FORCE)'))


def test_backfill_reports_each_existing_failed_job_once(database):
    from dojo.schema import initialize_database

    url, engine = database
    command.upgrade(config(url), "0014_emission_idempotency")
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO jobs
            (job_id, kind, status, payload, created_at, finished_at)
            VALUES ('j-1', 'media.process', 'failed', '{}',
                    '2026-09-01 10:00+00', '2026-09-02 11:00+00'),
                   ('j-2', 'render', 'failed', '{}', '2026-09-01 10:00+00', NULL),
                   ('j-3', 'render', 'done', '{}', '2026-09-01 10:00+00', NULL)"""))

    initialize_database(url)
    with engine.connect() as conn:
        alerts = conn.execute(text(
            "SELECT event_key, kind, title, body, data, created_at"
            "  FROM operational_alerts ORDER BY event_key"
        )).all()
        generations = dict(conn.execute(text(
            "SELECT job_id, failure_generation FROM jobs"
        )).all())
    assert [row[0] for row in alerts] == ["job:j-1:failure:1", "job:j-2:failure:1"]
    assert generations == {"j-1": 1, "j-2": 1, "j-3": 0}
    finished, never_finished = alerts
    assert finished[5].isoformat() == "2026-09-02T11:00:00+00:00"  # finished_at wins
    assert never_finished[5].isoformat() == "2026-09-01T10:00:00+00:00"  # falls back
    for event_key, kind, title, body, data, _ in alerts:
        assert kind == "job.failed" and title == "İş başarısız oldu"
        assert data["type"] == "operational_alert" and data["alert_id"]
        assert event_key.endswith(":failure:1")
    assert finished[3] == "media.process işi başarısız oldu. İş no: j-1"
    assert never_finished[3] == "render işi başarısız oldu. İş no: j-2"


def test_backfill_is_idempotent_across_reinitialization(database):
    from dojo.schema import initialize_database

    url, engine = database
    command.upgrade(config(url), "0014_emission_idempotency")
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO jobs (job_id, kind, status, payload, created_at)
            VALUES ('j-1', 'render', 'failed', '{}', now())"""))
    initialize_database(url)
    initialize_database(url)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM operational_alerts")) == 1
        assert conn.scalar(text("SELECT failure_generation FROM jobs")) == 1


def test_downgrade_removes_only_new_objects(database):
    url, engine = database
    command.upgrade(config(url), "head")
    command.downgrade(config(url), "0014_emission_idempotency")
    with engine.connect() as conn:
        assert "monitoring_incidents" not in set(inspect(engine).get_table_names())
        assert "failure_generation" not in {
            c["name"] for c in inspect(engine).get_columns("jobs")
        }
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) \
            == "0014_emission_idempotency"
    command.upgrade(config(url), "head")
    assert_head(engine)


def test_legacy_adoption_replays_backfill_for_failed_history(database):
    """An unversioned pre-0015 create_all database still reports its history."""
    from dojo.schema import initialize_database

    url, engine = database
    legacy(engine)
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO jobs (job_id, kind, status, payload, created_at)
            VALUES ('j-1', 'render', 'failed', '{}', now())"""))
    initialize_database(url)
    assert_head(engine)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM operational_alerts")) == 1
        assert conn.scalar(text("SELECT failure_generation FROM jobs")) == 1


def test_initializer_fresh_and_repeat(database):
    from dojo.schema import initialize_database

    url, engine = database
    initialize_database(url)
    assert_head(engine)


def test_current_create_all_schema_can_be_initialized(database):
    from dojo.schema import initialize_database

    url, engine = database
    Base.metadata.create_all(engine)
    initialize_database(url)
    assert_head(engine)
    initialize_database(url)
    assert_head(engine)


def test_initializer_upgrades_versioned_database(database):
    from dojo.schema import initialize_database

    url, engine = database
    command.upgrade(config(url), "0012_meta_connection")
    initialize_database(url)
    assert_head(engine)
    assert "connection_type" in {c["name"] for c in inspect(engine).get_columns("meta_connections")}


def test_recognized_unversioned_baseline_preserves_history(database):
    from dojo.schema import initialize_database

    url, engine = database
    legacy(engine)
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO audit_events (action, actor, occurred_at, details)
                             VALUES ('history', 'test', now(), '{}')"""))
    initialize_database(url)
    assert_head(engine)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT action FROM audit_events")) == "history"


@pytest.mark.parametrize("damage", [
    "missing_column", "missing_unique", "wrong_predicate", "missing_pk",
])
def test_unsupported_legacy_schema_rejected_without_stamp(database, damage):
    from dojo.schema import initialize_database

    url, engine = database
    legacy(engine)
    commands = {
        "missing_column": "ALTER TABLE jobs DROP COLUMN error_reason",
        "missing_unique": "ALTER TABLE jobs DROP CONSTRAINT jobs_job_id_key",
        "wrong_predicate": "DROP INDEX ix_packages_status_active",
        "missing_pk": "ALTER TABLE audit_events DROP CONSTRAINT audit_events_pkey",
    }
    with engine.begin() as conn:
        conn.execute(text(commands[damage]))
        if damage == "wrong_predicate":
            conn.execute(text("CREATE UNIQUE INDEX ix_packages_status_active "
                              "ON packages(status) WHERE status = 'completed'"))
    with pytest.raises(RuntimeError, match="Unsupported unversioned schema"):
        initialize_database(url)
    assert "alembic_version" not in inspect(engine).get_table_names()
    assert "uq_jobs_active_render" not in {i["name"] for i in inspect(engine).get_indexes("jobs")}


@pytest.mark.parametrize("versioned", [False, True])
def test_conflict_preflight_reports_ids_and_preserves_every_row(database, versioned):
    from dojo.schema import initialize_database

    url, engine = database
    if versioned:
        command.upgrade(config(url), "0013_instagram_login")
    else:
        legacy(engine)
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO yayin_zamani (id, kind, due_at, status, created_at)
            VALUES (41, 'regular', '2026-01-01', 'pending', now()),
                   (42, 'regular', '2026-01-01', 'pending', now())"""))
        conn.execute(text("""INSERT INTO jobs (id, job_id, kind, status, payload, created_at)
            VALUES (51, 'a', 'render', 'queued', '{"package":"p","digest":"d"}', now()),
                   (52, 'b', 'render', 'processing', '{"package":"p","digest":"d"}', now())"""))
    with pytest.raises(RuntimeError) as failure:
        initialize_database(url)
    message = str(failure.value)
    assert all(value in message for value in ("41", "42", "51", "52", "jobs", "yayin_zamani"))
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM jobs")) == 2
        assert conn.scalar(text("SELECT count(*) FROM yayin_zamani")) == 2
        if versioned:
            version = conn.scalar(text("SELECT version_num FROM alembic_version"))
            assert version == "0013_instagram_login"
    if not versioned:
        assert "alembic_version" not in inspect(engine).get_table_names()


def test_initializer_cli_serializes_processes_and_honors_env(database, tmp_path):
    url, engine = database
    env = {**os.environ, "DATABASE_URL": url}

    def run():
        return subprocess.run([sys.executable, "-m", "dojo.schema"], cwd=tmp_path,
                              env=env, capture_output=True, text=True, timeout=45)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert [r.returncode for r in results] == [0, 0], [r.stderr for r in results]
    assert_head(engine)


def test_alembic_env_database_url_overrides_config(database, monkeypatch):
    url, engine = database
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = config("postgresql+psycopg://unused:unused@127.0.0.1:1/unused?connect_timeout=2")
    command.upgrade(cfg, "head")
    assert_head(engine)


def test_review_conflicts_reported_without_history_deletion(database):
    from dojo.schema import initialize_database

    url, engine = database
    legacy(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE yayin_incelemesi "
                          "DROP CONSTRAINT uq_yayin_incelemesi_occ_rev"))
        conn.execute(text("""INSERT INTO yayin_incelemesi
            (id, occurrence_id, package_folder, revision_digest, status, created_at, version)
            VALUES (61, 1, 'p', 'd', 'pending', now(), 1),
                   (62, 1, 'p', 'd', 'pending', now(), 1)"""))
    with pytest.raises(RuntimeError, match=r"yayin_incelemesi: row IDs \[61, 62\]"):
        initialize_database(url)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM yayin_incelemesi")) == 2
    assert "alembic_version" not in inspect(engine).get_table_names()


def test_installed_wheel_initializer_from_unrelated_directory(database, tmp_path):
    url, engine = database
    root = Path(__file__).resolve().parents[2]
    wheel_dir = tmp_path / "wheels"
    built = subprocess.run(
        ["uv", "build", "--package", "dojo-core", "--wheel", "--out-dir", str(wheel_dir)],
        cwd=root, capture_output=True, text=True, timeout=60,
    )
    assert built.returncode == 0, built.stderr
    target = tmp_path / "installed"
    installed = subprocess.run(
        ["uv", "pip", "install", "--no-deps", "--target", str(target),
         str(next(wheel_dir.glob("*.whl")))],
        capture_output=True, text=True, timeout=60,
    )
    assert installed.returncode == 0, installed.stderr
    # The installed wheel must provide migrations; no checkout fallback exists here.
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(target)}
    result = subprocess.run(
        [sys.executable, "-c",
         "import dojo.schema as s; from pathlib import Path; "
         "assert Path(s.__file__).is_relative_to(Path('installed').resolve()); s.main()"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert_head(engine)
