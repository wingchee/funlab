import os
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
os.environ.setdefault("APP_ENV", "test")
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import database  # noqa: E402
import models  # noqa: E402


@pytest.mark.parametrize("connection_kind", ["application", "migration"])
def test_every_sqlite_engine_enables_foreign_keys(tmp_path, connection_kind):
    engine = create_engine(f"sqlite:///{tmp_path / f'{connection_kind}.db'}")
    database.configure_sqlite_foreign_keys(engine)

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (models.MemberPackage, {"member_id": 999, "package_name": "Orphan", "total_seconds": 1, "remaining_seconds": 1}),
        (models.Favorite, {"user_id": 999, "pattern_id": 999}),
        (models.TableTimer, {"table_number": 99, "active_member_id": 999}),
        (models.TableTimeLog, {"table_number": 99, "member_id": 999, "started_at": datetime(2026, 1, 1), "ended_at": datetime(2026, 1, 1)}),
        (models.MemberVisit, {"member_id": 999, "table_number": 99, "checked_in_at": datetime(2026, 1, 1), "checked_out_at": datetime(2026, 1, 1)}),
    ],
)
def test_orphan_membership_references_fail_with_integrity_error(tmp_path, model, values):
    engine = create_engine(f"sqlite:///{tmp_path / 'constraints.db'}")
    database.configure_sqlite_foreign_keys(engine)
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(model(**values))

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
