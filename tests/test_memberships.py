import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
os.environ.setdefault("APP_ENV", "test")
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import models  # noqa: E402
import schemas  # noqa: E402
from auth import get_membership_user, hash_password  # noqa: E402
from routers import timetable  # noqa: E402


class MembershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.memberships = importlib.import_module("routers.memberships")
        except ModuleNotFoundError as exc:
            cls.memberships = None
            cls.import_error = exc

    def _session(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        models.Base.metadata.create_all(bind=engine)
        return sessionmaker(bind=engine)()

    def _memberships(self):
        if self.memberships is None:
            self.fail(f"routers.memberships module is required: {self.import_error}")
        return self.memberships

    def _member(self, db, *, name="Member", phone="60123456789", **overrides):
        values = {
            "email": f"{phone}@example.com",
            "password_hash": hash_password("member-pass"),
            "name": name,
            "is_admin": False,
            "member_code": f"FL{int(phone[-8:]):08d}",
            "phone": phone,
            "is_active": True,
            "notes": "",
        }
        values.update(overrides)
        member = models.User(**values)
        db.add(member)
        db.commit()
        db.refresh(member)
        return member

    def test_membership_routes_do_not_expose_auth_aliases(self):
        source = (BACKEND / "routers" / "memberships.py").read_text()
        self.assertNotIn('@router.post("/register")', source)
        self.assertNotIn('@router.post("/login")', source)
        self.assertNotIn("def register_member", source)
        self.assertNotIn("def login_member", source)
        self.assertNotIn("member_auth", source)
        self.assertNotRegex(source, r"models\.Member\b")

    def test_member_code_is_searchable_by_name_email_phone_or_code(self):
        db = self._session()
        memberships = self._memberships()
        alice = self._member(db, name="Alice Tan", phone="60123456781")
        bob = self._member(db, name="Bob Lee", phone="60129998887")
        self.assertEqual(memberships.search_members(db, "alice")[0].id, alice.id)
        self.assertEqual(memberships.search_members(db, alice.email)[0].id, alice.id)
        self.assertEqual(memberships.search_members(db, "999888")[0].id, bob.id)
        self.assertEqual(memberships.search_members(db, alice.member_code)[0].id, alice.id)

    def test_staff_search_finds_admin_only_account_by_name_or_email(self):
        db = self._session()
        memberships = self._memberships()
        admin = models.User(
            email="owner@example.com",
            password_hash=hash_password("admin-pass"),
            name="Studio Owner",
            is_admin=True,
            is_active=True,
            notes="",
        )
        db.add(admin)
        db.commit()

        self.assertEqual(memberships.search_members(db, "Studio Owner")[0].id, admin.id)
        self.assertEqual(memberships.search_members(db, "owner@example.com")[0].id, admin.id)

    def test_staff_can_promote_admin_to_dual_capability_and_remove_empty_membership(self):
        db = self._session()
        memberships = self._memberships()
        admin = models.User(
            email="owner@example.com",
            password_hash=hash_password("admin-pass"),
            name="Owner",
            is_admin=True,
            is_active=True,
            notes="keep account",
        )
        db.add(admin)
        db.commit()

        promoted = memberships.admin_promote_membership(
            admin.id,
            schemas.MembershipPromotion(phone="+60 12-345 6789"),
            _=None,
            db=db,
        )

        self.assertRegex(promoted["member_code"], r"^FL\d{8}$")
        self.assertEqual(promoted["phone"], "60123456789")
        db.refresh(admin)
        self.assertTrue(admin.is_admin)
        self.assertIs(get_membership_user(admin), admin)

        removed = memberships.admin_remove_membership(admin.id, _=None, db=db)
        self.assertTrue(removed["is_admin"])
        self.assertIsNone(removed["member_code"])
        self.assertIsNone(removed["phone"])
        self.assertEqual(admin.email, "owner@example.com")

    def test_staff_membership_promotion_requires_unique_valid_phone(self):
        db = self._session()
        memberships = self._memberships()
        self._member(db, phone="60123456789")
        admin = models.User(
            email="owner@example.com",
            password_hash=hash_password("admin-pass"),
            name="Owner",
            is_admin=True,
            is_active=True,
            notes="",
        )
        db.add(admin)
        db.commit()

        for phone in ("---", "+60 12-345 6789"):
            with self.subTest(phone=phone), self.assertRaises(HTTPException) as raised:
                memberships.admin_promote_membership(
                    admin.id,
                    schemas.MembershipPromotion(phone=phone),
                    _=None,
                    db=db,
                )
            self.assertIn(raised.exception.status_code, (400, 409))

    def test_staff_cannot_remove_membership_with_retained_references(self):
        db = self._session()
        memberships = self._memberships()
        member = self._member(db, phone="60123456789")
        memberships.add_package_record(db, member, "Hours", 3600)

        with self.assertRaises(HTTPException) as raised:
            memberships.admin_remove_membership(member.id, _=None, db=db)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("package", raised.exception.detail.lower())
        db.refresh(member)
        self.assertIsNotNone(member.member_code)

    def test_member_self_service_operations_use_membership_capable_user(self):
        db = self._session()
        memberships = self._memberships()
        member = self._member(db)
        memberships.add_package_record(db, member, "Hours", 3600)
        db.add(models.MemberVisit(
            member_id=member.id,
            table_number=1,
            checked_in_at=datetime(2026, 1, 1),
            checked_out_at=datetime(2026, 1, 1, 1),
        ))
        db.commit()
        self.assertEqual(memberships.member_me(member)["id"], member.id)
        self.assertEqual(len(memberships.member_my_packages(member)), 1)
        self.assertEqual(len(memberships.member_my_visits(member)), 1)
        self.assertEqual(memberships.member_my_qr(member).media_type, "image/png")

        admin_only = models.User(
            email="admin@example.com",
            password_hash="unused",
            name="Admin",
            is_admin=True,
        )
        with self.assertRaises(HTTPException) as raised:
            get_membership_user(admin_only)
        self.assertEqual(raised.exception.status_code, 403)

    def test_package_deduction_uses_oldest_hours_then_records_extra_due(self):
        db = self._session()
        memberships = self._memberships()
        member = self._member(db, name="Chris Wong", phone="60120000010")
        memberships.add_package_record(db, member, package_name="Starter", total_seconds=1800)
        memberships.add_package_record(db, member, package_name="Ten Hour", total_seconds=3600)

        result = memberships.deduct_member_seconds(db, member, charged_seconds=5400)

        self.assertEqual(result["deducted_seconds"], 5400)
        self.assertEqual(result["extra_due_seconds"], 0)
        packages = db.query(models.MemberPackage).order_by(models.MemberPackage.id.asc()).all()
        self.assertEqual([pkg.remaining_seconds for pkg in packages], [0, 0])

        result = memberships.deduct_member_seconds(db, member, charged_seconds=1800)

        self.assertEqual(result["deducted_seconds"], 0)
        self.assertEqual(result["extra_due_seconds"], 1800)

    def test_stopping_member_table_creates_visit_and_deducts_charged_time(self):
        db = self._session()
        memberships = self._memberships()
        now = datetime(2026, 5, 3, 12, 0, 0)
        member = self._member(db, name="Dana Lim", phone="60120000011")
        package = memberships.add_package_record(db, member, package_name="Ten Hour", total_seconds=10 * 3600)
        db.add(models.TableTimer(
            table_number=1,
            is_running=True,
            elapsed_seconds=0,
            started_at=now - timedelta(seconds=4201),
            active_member_id=member.id,
        ))
        db.commit()

        payload = timetable.stop_table(1, _=None, db=db, now=now)

        self.assertIsNone(payload["active_member"])
        visits = db.query(models.MemberVisit).all()
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0].member_id, member.id)
        self.assertEqual(visits[0].charged_seconds, 5400)
        self.assertEqual(visits[0].package_deducted_seconds, 5400)
        self.assertEqual(visits[0].extra_due_seconds, 0)
        db.refresh(package)
        self.assertEqual(package.remaining_seconds, (10 * 3600) - 5400)

    def test_member_attached_mid_session_is_charged_only_from_check_in(self):
        db = self._session()
        memberships = self._memberships()
        started_at = datetime(2026, 5, 3, 12, 0, 0)
        checked_in_at = started_at + timedelta(minutes=30)
        stopped_at = started_at + timedelta(minutes=75)
        member = self._member(db, name="Mid Session", phone="60120000001")
        package = memberships.add_package_record(db, member, package_name="Ten Hour", total_seconds=10 * 3600)
        db.add(models.TableTimer(
            table_number=1,
            is_running=True,
            elapsed_seconds=0,
            started_at=started_at,
        ))
        db.commit()

        timetable.attach_member_to_table(
            1,
            schemas.TableMemberAttachRequest(member_code=member.member_code),
            _=None,
            db=db,
            now=checked_in_at,
        )
        timetable.stop_table(1, _=None, db=db, now=stopped_at)

        log = db.query(models.TableTimeLog).one()
        visit = db.query(models.MemberVisit).one()
        self.assertEqual(log.occupied_seconds, 75 * 60)
        self.assertEqual(log.charged_seconds, 90 * 60)
        self.assertEqual(visit.checked_in_at, checked_in_at)
        self.assertEqual(visit.occupied_seconds, 45 * 60)
        self.assertEqual(visit.charged_seconds, 60 * 60)
        self.assertEqual(visit.package_deducted_seconds, 60 * 60)
        db.refresh(package)
        self.assertEqual(package.remaining_seconds, (10 * 3600) - (60 * 60))

    def test_running_table_rejects_replacing_or_detaching_attached_member(self):
        db = self._session()
        memberships = self._memberships()
        first = self._member(db, name="First Member", phone="60120000002")
        second = self._member(db, name="Second Member", phone="60120000003")
        started_at = datetime(2026, 5, 3, 12, 0, 0)
        db.add(models.TableTimer(
            table_number=1,
            is_running=True,
            elapsed_seconds=0,
            started_at=started_at,
            active_member_id=first.id,
            active_member_started_at=started_at,
        ))
        db.commit()

        for member_code in (second.member_code, ""):
            with self.subTest(member_code=member_code), self.assertRaises(HTTPException) as raised:
                timetable.attach_member_to_table(
                    1,
                    schemas.TableMemberAttachRequest(member_code=member_code),
                    _=None,
                    db=db,
                    now=started_at + timedelta(minutes=5),
                )
            self.assertEqual(raised.exception.status_code, 409)

    def test_duplicate_stop_from_stale_session_settles_only_once(self):
        memberships = self._memberships()
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'settlement.db'}",
                connect_args={"check_same_thread": False},
            )
            models.Base.metadata.create_all(bind=engine)
            Session = sessionmaker(bind=engine)
            setup_db = Session()
            member = self._member(setup_db, name="One Charge", phone="60120000004")
            package = memberships.add_package_record(
                setup_db,
                member,
                package_name="Ten Hour",
                total_seconds=10 * 3600,
            )
            package_id = package.id
            started_at = datetime(2026, 5, 3, 12, 0, 0)
            setup_db.add(models.TableTimer(
                table_number=1,
                is_running=True,
                elapsed_seconds=0,
                started_at=started_at,
                active_member_id=member.id,
                active_member_started_at=started_at,
            ))
            setup_db.commit()
            setup_db.close()

            first_db = Session()
            stale_db = Session()
            stale_timer = timetable._get_table(stale_db, 1)
            stopped_at = started_at + timedelta(minutes=65)

            timetable.stop_table(1, _=None, db=first_db, now=stopped_at)
            stale_result = timetable._settle_running_timer(
                stale_timer,
                stale_db,
                stopped_at,
                reset_elapsed=False,
            )
            stale_db.commit()

            check_db = Session()
            self.assertIsNone(stale_result)
            self.assertEqual(check_db.query(models.TableTimeLog).count(), 1)
            self.assertEqual(check_db.query(models.MemberVisit).count(), 1)
            refreshed_package = check_db.query(models.MemberPackage).filter_by(id=package_id).one()
            self.assertEqual(refreshed_package.remaining_seconds, (10 * 3600) - (60 * 60))
            first_db.close()
            stale_db.close()
            check_db.close()

    def test_stale_stop_does_not_claim_restarted_run(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'aba.db'}",
                connect_args={"check_same_thread": False},
            )
            models.Base.metadata.create_all(bind=engine)
            Session = sessionmaker(bind=engine)
            setup_db = Session()
            started_at = datetime(2026, 5, 3, 12, 0, 0)
            setup_db.add(models.TableTimer(
                table_number=1,
                is_running=True,
                elapsed_seconds=0,
                started_at=started_at,
                run_token="run-a",
                state_version=1,
            ))
            setup_db.commit()
            setup_db.close()

            winner_db = Session()
            stale_db = Session()
            stale_timer = timetable._get_table(stale_db, 1)
            timetable.stop_table(
                1,
                _=None,
                db=winner_db,
                now=started_at + timedelta(minutes=20),
            )
            restarted = timetable._get_table(winner_db, 1)
            restarted.is_running = True
            restarted.started_at = started_at + timedelta(minutes=21)
            restarted.run_token = "run-b"
            restarted.state_version += 1
            winner_db.commit()

            stale_result = timetable._settle_running_timer(
                stale_timer,
                stale_db,
                started_at + timedelta(minutes=25),
                reset_elapsed=False,
            )
            stale_db.commit()

            check_db = Session()
            current = timetable._get_table(check_db, 1)
            self.assertIsNone(stale_result)
            self.assertTrue(current.is_running)
            self.assertEqual(current.run_token, "run-b")
            self.assertEqual(check_db.query(models.TableTimeLog).count(), 1)
            winner_db.close()
            stale_db.close()
            check_db.close()

    def test_stop_retries_same_run_when_member_attaches_after_snapshot(self):
        memberships = self._memberships()
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'attach-race.db'}",
                connect_args={"check_same_thread": False},
            )
            models.Base.metadata.create_all(bind=engine)
            Session = sessionmaker(bind=engine)
            setup_db = Session()
            member = self._member(
                setup_db,
                name="Attach Race",
                phone="60120000008",
            )
            memberships.add_package_record(
                setup_db,
                member,
                package_name="Ten Hour",
                total_seconds=10 * 3600,
            )
            started_at = datetime(2026, 5, 3, 12, 0, 0)
            setup_db.add(models.TableTimer(
                table_number=1,
                is_running=True,
                elapsed_seconds=0,
                started_at=started_at,
                run_token="same-run",
                state_version=1,
            ))
            setup_db.commit()
            member_code = member.member_code
            setup_db.close()

            stale_db = Session()
            attach_db = Session()
            stale_timer = timetable._get_table(stale_db, 1)
            checked_in_at = started_at + timedelta(minutes=30)
            timetable.attach_member_to_table(
                1,
                schemas.TableMemberAttachRequest(member_code=member_code),
                _=None,
                db=attach_db,
                now=checked_in_at,
            )

            log = timetable._settle_running_timer(
                stale_timer,
                stale_db,
                started_at + timedelta(minutes=50),
                reset_elapsed=False,
            )
            stale_db.commit()

            self.assertIsNotNone(log)
            visit = stale_db.query(models.MemberVisit).one()
            self.assertEqual(visit.checked_in_at, checked_in_at)
            self.assertEqual(visit.occupied_seconds, 20 * 60)
            self.assertEqual(visit.charged_seconds, 60 * 60)
            stale_db.close()
            attach_db.close()

    def test_package_deduction_query_requests_row_lock(self):
        db = self._session()
        memberships = self._memberships()
        member = self._member(db, name="Locked Balance", phone="60120000005")

        query = memberships._member_packages_for_update(db, member.id)

        self.assertIsNotNone(query._for_update_arg)

    def test_admin_set_cannot_stop_member_table_without_settlement(self):
        db = self._session()
        memberships = self._memberships()
        started_at = datetime(2026, 5, 3, 12, 0, 0)
        stopped_at = started_at + timedelta(minutes=20)
        member = self._member(db, name="Admin Stop", phone="60120000006")
        memberships.add_package_record(db, member, package_name="Ten Hour", total_seconds=10 * 3600)
        db.add(models.TableTimer(
            table_number=1,
            is_running=True,
            elapsed_seconds=0,
            started_at=started_at,
            active_member_id=member.id,
            active_member_started_at=started_at,
        ))
        db.commit()

        timetable.set_table(
            1,
            schemas.TableTimerSetRequest(elapsed_seconds=0, is_running=False),
            _=None,
            db=db,
            now=stopped_at,
        )

        self.assertEqual(db.query(models.TableTimeLog).count(), 1)
        visit = db.query(models.MemberVisit).one()
        self.assertEqual(visit.member_id, member.id)
        self.assertEqual(visit.charged_seconds, 60 * 60)

    def test_admin_update_rejects_phone_that_normalizes_to_empty(self):
        db = self._session()
        memberships = self._memberships()
        member = self._member(db, name="Valid Phone", phone="60120000007")

        with self.assertRaises(HTTPException) as raised:
            memberships.admin_update_member(
                member.id,
                schemas.MemberUpdate(phone="---"),
                _=None,
                db=db,
            )

        self.assertEqual(raised.exception.status_code, 400)
        db.refresh(member)
        self.assertEqual(member.phone, "60120000007")
