import json
import os
import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
os.environ.setdefault("APP_ENV", "test")
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import models  # noqa: E402
from routers import favorites  # noqa: E402


class MemberFavoriteTests(unittest.TestCase):
    def _session(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        models.Base.metadata.create_all(bind=engine)
        return sessionmaker(bind=engine)()

    def _pattern(self, title: str) -> models.Pattern:
        return models.Pattern(
            title=title,
            tags=json.dumps(["Test"]),
            size="Small",
            grid_w=1,
            grid_h=1,
            faves_count=0,
            preview_color="#F47A8A",
            palette=json.dumps([]),
            grid_data=json.dumps([[""]]),
        )

    def test_unified_users_toggle_favorites_isolated_by_owner(self):
        db = self._session()
        member_user = models.User(
            member_code="FL00000001",
            email="member@example.com",
            password_hash="unused",
            name="Member",
            phone="60120000001",
            is_active=True,
            notes="",
        )
        admin_user = models.User(
            email="admin@example.com",
            password_hash="unused",
            name="Admin",
            is_admin=True,
        )
        member_pattern = self._pattern("Member Pattern")
        user_pattern = self._pattern("User Pattern")
        db.add_all([member_user, admin_user, member_pattern, user_pattern])
        db.commit()
        db.refresh(member_user)
        db.refresh(admin_user)
        db.refresh(member_pattern)
        db.refresh(user_pattern)

        result = favorites.toggle_favorite(
            member_pattern.id, current_user=member_user, db=db
        )
        self.assertTrue(result["favorited"])
        db.query(models.Favorite).filter_by(
            user_id=member_user.id, pattern_id=member_pattern.id
        ).one()

        user_result = favorites.toggle_favorite(
            user_pattern.id,
            current_user=admin_user,
            db=db,
        )
        self.assertTrue(user_result["favorited"])
        self.assertEqual(
            favorites.list_favorite_ids(current_user=member_user, db=db),
            [member_pattern.id],
        )
        self.assertEqual(
            favorites.list_favorite_ids(current_user=admin_user, db=db),
            [user_pattern.id],
        )

        removed = favorites.toggle_favorite(
            member_pattern.id, current_user=member_user, db=db
        )
        self.assertFalse(removed["favorited"])
        self.assertEqual(favorites.list_favorite_ids(current_user=member_user, db=db), [])
        self.assertEqual(
            favorites.list_favorite_ids(current_user=admin_user, db=db),
            [user_pattern.id],
        )


if __name__ == "__main__":
    unittest.main()
