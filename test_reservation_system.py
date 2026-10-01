"""Verification tests for Meeting Room Reservation System covering all 5 core business rules."""

import unittest
from datetime import datetime, timedelta

from reservation_system.models import (
    Room,
    Reservation,
    ReservationStatus,
    MaintenanceStatus,
    RecurrenceFrequency,
    RecurrencePolicy,
    RecurrenceRule,
    TimeOverlapError,
    BufferTimeViolationError,
    MaintenanceConflictError,
    RecurrenceConflictError,
    InvalidStateTransitionError,
    TimeSlotInvalidError,
)
from reservation_system.reservation_service import ReservationService


class TestMeetingRoomReservationSystem(unittest.TestCase):
    """Test suite validating all 5 core rules and system invariants."""

    def setUp(self):
        """Set up fresh service and sample rooms before each test."""
        self.service = ReservationService()
        self.room_a = Room(
            room_id="ROOM-101",
            name="Tokyo Executive Boardroom",
            capacity=12,
            buffer_minutes=15,
            equipment=["Projector", "Video Conference", "Whiteboard"],
        )
        self.room_b = Room(
            room_id="ROOM-102",
            name="Kyoto Discussion Hub",
            capacity=6,
            buffer_minutes=10,
            equipment=["TV Screen", "Whiteboard"],
        )
        self.service.add_room(self.room_a)
        self.service.add_room(self.room_b)

        # Baseline date: 2026-10-05 (Monday)
        self.base_date = datetime(2026, 10, 5, 9, 0, 0)

    # =========================================================================
    # Rule 1: 時段重疊 (Time Overlap)
    # =========================================================================

    def test_rule1_exact_overlap_fails(self):
        """Rule 1: Prevent booking during the exact same time slot."""
        start = self.base_date.replace(hour=10, minute=0)
        end = self.base_date.replace(hour=11, minute=0)

        # First booking succeeds
        res1 = self.service.create_reservation(
            room_id="ROOM-101",
            organizer_id="alice",
            title="Q3 Architecture Review",
            start_time=start,
            end_time=end,
        )
        self.assertEqual(res1.status, ReservationStatus.CONFIRMED)

        # Second booking with identical time slot MUST raise TimeOverlapError
        with self.assertRaises(TimeOverlapError) as ctx:
            self.service.create_reservation(
                room_id="ROOM-101",
                organizer_id="bob",
                title="Sprint Planning",
                start_time=start,
                end_time=end,
            )
        self.assertIn("Direct time overlap", str(ctx.exception))
        self.assertEqual(ctx.exception.conflicting_id, res1.reservation_id)

    def test_rule1_partial_overlap_start_and_end(self):
        """Rule 1: Prevent bookings that partially overlap the start or end."""
        # Existing: 14:00 - 16:00
        start = self.base_date.replace(hour=14, minute=0)
        end = self.base_date.replace(hour=16, minute=0)
        self.service.create_reservation("ROOM-101", "alice", "Team Sync", start, end)

        # Candidate 1: Overlaps existing start (13:30 - 14:30)
        with self.assertRaises(TimeOverlapError):
            self.service.create_reservation(
                "ROOM-101", "bob", "Client Pitch",
                self.base_date.replace(hour=13, minute=30),
                self.base_date.replace(hour=14, minute=30),
            )

        # Candidate 2: Overlaps existing end (15:30 - 16:30)
        with self.assertRaises(TimeOverlapError):
            self.service.create_reservation(
                "ROOM-101", "charlie", "1-on-1",
                self.base_date.replace(hour=15, minute=30),
                self.base_date.replace(hour=16, minute=30),
            )

    def test_rule1_subset_and_superset_overlap(self):
        """Rule 1: Prevent booking that is enclosed inside or encloses an existing slot."""
        # Existing: 10:00 - 12:00
        start = self.base_date.replace(hour=10, minute=0)
        end = self.base_date.replace(hour=12, minute=0)
        self.service.create_reservation("ROOM-101", "alice", "All-Hands", start, end)

        # Candidate subset: 10:30 - 11:30
        with self.assertRaises(TimeOverlapError):
            self.service.create_reservation(
                "ROOM-101", "bob", "Quick Standup",
                self.base_date.replace(hour=10, minute=30),
                self.base_date.replace(hour=11, minute=30),
            )

        # Candidate superset: 09:30 - 12:30
        with self.assertRaises(TimeOverlapError):
            self.service.create_reservation(
                "ROOM-101", "charlie", "Workshop",
                self.base_date.replace(hour=9, minute=30),
                self.base_date.replace(hour=12, minute=30),
            )

    def test_rule1_different_room_same_time_succeeds(self):
        """Rule 1: Booking in a different room at the same time is completely allowed."""
        start = self.base_date.replace(hour=10, minute=0)
        end = self.base_date.replace(hour=11, minute=0)

        res_a = self.service.create_reservation("ROOM-101", "alice", "Design Thinking", start, end)
        res_b = self.service.create_reservation("ROOM-102", "bob", "Design Thinking 2", start, end)

        self.assertEqual(res_a.room_id, "ROOM-101")
        self.assertEqual(res_b.room_id, "ROOM-102")

    # =========================================================================
    # Rule 2: 緩衝時間 (Buffer Time)
    # =========================================================================

    def test_rule2_zero_gap_back_to_back_violates_buffer(self):
        """Rule 2: Back-to-back booking with 0 gap fails due to mandatory transition buffer."""
        # Existing: 10:00 - 11:00 (ROOM-101 has 15 mins buffer)
        self.service.create_reservation(
            "ROOM-101", "alice", "Morning Strategy",
            self.base_date.replace(hour=10, minute=0),
            self.base_date.replace(hour=11, minute=0),
        )

        # Candidate starts right at 11:00 (gap is 0m, required 15m)
        with self.assertRaises(BufferTimeViolationError) as ctx:
            self.service.create_reservation(
                "ROOM-101", "bob", "Afternoon Strategy",
                self.base_date.replace(hour=11, minute=0),
                self.base_date.replace(hour=12, minute=0),
            )
        self.assertIn("Buffer time violation", str(ctx.exception))
        self.assertEqual(ctx.exception.required_buffer, 15)

    def test_rule2_insufficient_buffer_gap_fails(self):
        """Rule 2: Booking with gap less than required buffer (e.g., 10m < 15m) fails."""
        # Existing: 10:00 - 11:00
        self.service.create_reservation(
            "ROOM-101", "alice", "Design Critique",
            self.base_date.replace(hour=10, minute=0),
            self.base_date.replace(hour=11, minute=0),
        )

        # Candidate starts at 11:10 (gap is 10 mins < 15 mins)
        with self.assertRaises(BufferTimeViolationError):
            self.service.create_reservation(
                "ROOM-101", "bob", "Client Call",
                self.base_date.replace(hour=11, minute=10),
                self.base_date.replace(hour=12, minute=0),
            )

        # Candidate ends at 09:50 before 10:00 (gap is 10 mins < 15 mins)
        with self.assertRaises(BufferTimeViolationError):
            self.service.create_reservation(
                "ROOM-101", "charlie", "Early Sync",
                self.base_date.replace(hour=9, minute=0),
                self.base_date.replace(hour=9, minute=50),
            )

    def test_rule2_sufficient_buffer_gap_succeeds(self):
        """Rule 2: Booking with gap exactly equal to or greater than buffer succeeds."""
        # Existing: 10:00 - 11:00 (Buffer: 15m)
        self.service.create_reservation(
            "ROOM-101", "alice", "Session 1",
            self.base_date.replace(hour=10, minute=0),
            self.base_date.replace(hour=11, minute=0),
        )

        # Candidate 1: Exactly 15 minutes after (11:15 - 12:15) -> SUCCEEDS
        res1 = self.service.create_reservation(
            "ROOM-101", "bob", "Session 2",
            self.base_date.replace(hour=11, minute=15),
            self.base_date.replace(hour=12, minute=15),
        )
        self.assertEqual(res1.status, ReservationStatus.CONFIRMED)

        # Candidate 2: Exactly 15 minutes before Session 1 (08:45 - 09:45) -> SUCCEEDS
        res0 = self.service.create_reservation(
            "ROOM-101", "charlie", "Session 0",
            self.base_date.replace(hour=8, minute=45),
            self.base_date.replace(hour=9, minute=45),
        )
        self.assertEqual(res0.status, ReservationStatus.CONFIRMED)

    # =========================================================================
    # Rule 3: 週期性會議 (Recurring Meetings)
    # =========================================================================

    def test_rule3_weekly_recurrence_success(self):
        """Rule 3: Recurring weekly meeting generated cleanly across 4 weeks."""
        rule = RecurrenceRule(
            frequency=RecurrenceFrequency.WEEKLY,
            interval=1,
            count=4,
            policy=RecurrencePolicy.ALL_OR_NOTHING,
        )

        start = self.base_date.replace(hour=14, minute=0)
        end = self.base_date.replace(hour=15, minute=0)

        reservations, conflicts = self.service.create_reservation(
            room_id="ROOM-101",
            organizer_id="alice",
            title="Weekly Tech Alignment",
            start_time=start,
            end_time=end,
            recurrence_rule=rule,
        )

        self.assertEqual(len(reservations), 4)
        self.assertEqual(len(conflicts), 0)
        # Verify weekly intervals
        for i in range(4):
            expected_start = start + timedelta(weeks=i)
            self.assertEqual(reservations[i].start_time, expected_start)
            self.assertEqual(reservations[i].recurrence_index, i)
            self.assertEqual(reservations[i].recurrence_id, reservations[0].recurrence_id)

    def test_rule3_recurrence_all_or_nothing_fails_on_conflict(self):
        """Rule 3: ALL_OR_NOTHING policy aborts entire series if any occurrence conflicts."""
        # Plant a conflict in Week 3 (base_date + 2 weeks)
        conflict_start = (self.base_date + timedelta(weeks=2)).replace(hour=14, minute=0)
        conflict_end = (self.base_date + timedelta(weeks=2)).replace(hour=15, minute=0)
        self.service.create_reservation(
            "ROOM-101", "charlie", "VIP Client Demo", conflict_start, conflict_end
        )

        # Attempt to book weekly recurring series for 4 weeks
        rule = RecurrenceRule(
            frequency=RecurrenceFrequency.WEEKLY,
            interval=1,
            count=4,
            policy=RecurrencePolicy.ALL_OR_NOTHING,
        )

        with self.assertRaises(RecurrenceConflictError) as ctx:
            self.service.create_reservation(
                room_id="ROOM-101",
                organizer_id="alice",
                title="Weekly Sync",
                start_time=self.base_date.replace(hour=14, minute=0),
                end_time=self.base_date.replace(hour=15, minute=0),
                recurrence_rule=rule,
            )

        # Verify no reservations were created for Alice (Atomicity / Rollback)
        alice_res = [r for r in self.service.list_reservations_for_room("ROOM-101") if r.organizer_id == "alice"]
        self.assertEqual(len(alice_res), 0)
        self.assertEqual(len(ctx.exception.failed_instances), 1)
        self.assertEqual(ctx.exception.failed_instances[0]["index"], 2)

    def test_rule3_recurrence_allow_partial(self):
        """Rule 3: ALLOW_PARTIAL policy books conflict-free occurrences and reports conflicts."""
        # Plant conflict in Week 2
        conflict_start = (self.base_date + timedelta(weeks=1)).replace(hour=14, minute=0)
        conflict_end = (self.base_date + timedelta(weeks=1)).replace(hour=15, minute=0)
        self.service.create_reservation("ROOM-101", "charlie", "Urgent Incident Review", conflict_start, conflict_end)

        rule = RecurrenceRule(
            frequency=RecurrenceFrequency.WEEKLY,
            interval=1,
            count=3,
            policy=RecurrencePolicy.ALLOW_PARTIAL,
        )

        created, conflicts = self.service.create_reservation(
            room_id="ROOM-101",
            organizer_id="alice",
            title="Weekly Team Retro",
            start_time=self.base_date.replace(hour=14, minute=0),
            end_time=self.base_date.replace(hour=15, minute=0),
            recurrence_rule=rule,
        )

        # 2 out of 3 created, 1 conflict reported
        self.assertEqual(len(created), 2)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["index"], 1)

    def test_rule3_cancel_entire_series(self):
        """Rule 3: Cancel all instances of a recurring series."""
        rule = RecurrenceRule(
            frequency=RecurrenceFrequency.WEEKLY,
            interval=1,
            count=3,
        )
        created, _ = self.service.create_reservation(
            "ROOM-101", "alice", "Weekly Project Review",
            self.base_date.replace(hour=10, minute=0),
            self.base_date.replace(hour=11, minute=0),
            recurrence_rule=rule,
        )
        series_id = created[0].recurrence_id

        cancelled_list = self.service.cancel_recurring_series(series_id, cancelled_by="alice")
        self.assertEqual(len(cancelled_list), 3)

        # All must be cancelled
        active = self.service.list_reservations_for_room("ROOM-101", active_only=True)
        self.assertEqual(len(active), 0)

    # =========================================================================
    # Rule 4: 臨時維護需求 (Temporary Maintenance)
    # =========================================================================

    def test_rule4_maintenance_locks_out_new_reservations(self):
        """Rule 4: Normal reservations are locked out during maintenance windows."""
        maint_start = self.base_date.replace(hour=13, minute=0)
        maint_end = self.base_date.replace(hour=17, minute=0)

        # Admin schedules HVAC maintenance
        maint, evicted = self.service.schedule_maintenance(
            room_id="ROOM-101",
            title="HVAC Air Duct Cleaning",
            start_time=maint_start,
            end_time=maint_end,
            reason="Air quality inspection",
            admin_id="admin_john",
        )
        self.assertEqual(maint.status, MaintenanceStatus.SCHEDULED)
        self.assertEqual(len(evicted), 0)

        # Normal user attempts to book during maintenance
        with self.assertRaises(MaintenanceConflictError) as ctx:
            self.service.create_reservation(
                "ROOM-101", "alice", "Sales Presentation",
                self.base_date.replace(hour=14, minute=0),
                self.base_date.replace(hour=15, minute=0),
            )
        self.assertIn("unavailable due to scheduled maintenance", str(ctx.exception))

    def test_rule4_maintenance_without_override_rejects_if_bookings_exist(self):
        """Rule 4: Scheduling maintenance on already-booked slot fails if override_affected=False."""
        # Alice already booked 14:00 - 15:00
        self.service.create_reservation(
            "ROOM-101", "alice", "Product Launch Review",
            self.base_date.replace(hour=14, minute=0),
            self.base_date.replace(hour=15, minute=0),
        )

        # Admin tries to schedule maintenance without override
        with self.assertRaises(MaintenanceConflictError) as ctx:
            self.service.schedule_maintenance(
                room_id="ROOM-101",
                title="Ceiling Lamp Replacement",
                start_time=self.base_date.replace(hour=13, minute=0),
                end_time=self.base_date.replace(hour=16, minute=0),
                reason="Broken fixture",
                admin_id="admin_john",
                override_affected=False,
            )
        self.assertIn("active reservation(s) during this window", str(ctx.exception))

    def test_rule4_maintenance_with_override_cancels_existing_bookings(self):
        """Rule 4: Admin can override conflicting bookings with override_affected=True."""
        # Alice already booked 14:00 - 15:00
        res = self.service.create_reservation(
            "ROOM-101", "alice", "Critical Strategy Session",
            self.base_date.replace(hour=14, minute=0),
            self.base_date.replace(hour=15, minute=0),
        )

        # Admin schedules urgent maintenance with override
        maint, evicted = self.service.schedule_maintenance(
            room_id="ROOM-101",
            title="Emergency Projector Repair",
            start_time=self.base_date.replace(hour=13, minute=30),
            end_time=self.base_date.replace(hour=15, minute=30),
            reason="Burnt lamp socket",
            admin_id="admin_john",
            override_affected=True,
        )

        self.assertEqual(len(evicted), 1)
        self.assertEqual(evicted[0].reservation_id, res.reservation_id)

        # Re-fetch reservation and check state
        updated_res = self.service.get_reservation(res.reservation_id)
        self.assertEqual(updated_res.status, ReservationStatus.CANCELLED_BY_MAINTENANCE)
        self.assertIn("Room maintenance override", updated_res.cancellation_reason)
        self.assertEqual(updated_res.cancelled_by, "admin_john")

    def test_rule4_cancelling_maintenance_frees_room(self):
        """Rule 4: Cancelling maintenance window immediately re-opens room."""
        maint_start = self.base_date.replace(hour=13, minute=0)
        maint_end = self.base_date.replace(hour=15, minute=0)

        maint, _ = self.service.schedule_maintenance(
            "ROOM-101", "Routine Cleaning", maint_start, maint_end, "Weekly cleaning", "admin_john"
        )

        # Cancel the maintenance
        self.service.cancel_maintenance(maint.maintenance_id, admin_id="admin_john")

        # Booking now succeeds!
        res = self.service.create_reservation(
            "ROOM-101", "bob", "Recovered Meeting Slot",
            maint_start, maint_end
        )
        self.assertEqual(res.status, ReservationStatus.CONFIRMED)

    # =========================================================================
    # Rule 5: 預約取消 (Reservation Cancellation)
    # =========================================================================

    def test_rule5_cancellation_releases_slot_and_buffer(self):
        """Rule 5: Cancelling a reservation immediately frees both time slot and buffer."""
        start = self.base_date.replace(hour=10, minute=0)
        end = self.base_date.replace(hour=11, minute=0)

        # Alice books 10:00 - 11:00
        res = self.service.create_reservation("ROOM-101", "alice", "Original Meeting", start, end)

        # Bob attempts to book overlapping slot (10:30 - 11:30) -> FAILS
        with self.assertRaises(TimeOverlapError):
            self.service.create_reservation(
                "ROOM-101", "bob", "Bob Meeting",
                self.base_date.replace(hour=10, minute=30),
                self.base_date.replace(hour=11, minute=30),
            )

        # Alice cancels reservation
        cancelled_res = self.service.cancel_reservation(
            res.reservation_id,
            cancelled_by="alice",
            reason="Client rescheduled to next month",
        )
        self.assertEqual(cancelled_res.status, ReservationStatus.CANCELLED)
        self.assertIsNotNone(cancelled_res.cancelled_at)
        self.assertEqual(cancelled_res.cancelled_by, "alice")

        # Bob books the exact same slot -> SUCCEEDS immediately!
        bob_res = self.service.create_reservation(
            "ROOM-101", "bob", "Bob Meeting", start, end
        )
        self.assertEqual(bob_res.status, ReservationStatus.CONFIRMED)

        # Charlie books a slot starting right at 11:15 (respecting buffer) -> SUCCEEDS!
        charlie_res = self.service.create_reservation(
            "ROOM-101", "charlie", "Charlie Meeting",
            self.base_date.replace(hour=11, minute=15),
            self.base_date.replace(hour=12, minute=15),
        )
        self.assertEqual(charlie_res.status, ReservationStatus.CONFIRMED)

    def test_rule5_double_cancellation_rejected(self):
        """Rule 5: Prevent cancelling an already cancelled reservation."""
        start = self.base_date.replace(hour=10, minute=0)
        end = self.base_date.replace(hour=11, minute=0)
        res = self.service.create_reservation("ROOM-101", "alice", "Meeting", start, end)

        self.service.cancel_reservation(res.reservation_id, cancelled_by="alice")

        # Attempt to cancel second time must raise InvalidStateTransitionError
        with self.assertRaises(InvalidStateTransitionError):
            self.service.cancel_reservation(res.reservation_id, cancelled_by="alice")

    # =========================================================================
    # Edge Cases & Input Validations
    # =========================================================================

    def test_edge_case_start_after_end(self):
        """Edge case: start_time >= end_time raises TimeSlotInvalidError."""
        start = self.base_date.replace(hour=11, minute=0)
        end = self.base_date.replace(hour=10, minute=0)
        with self.assertRaises(TimeSlotInvalidError):
            self.service.create_reservation("ROOM-101", "alice", "Bad Slot", start, end)

    def test_edge_case_zero_duration(self):
        """Edge case: start_time == end_time raises TimeSlotInvalidError."""
        time_pt = self.base_date.replace(hour=10, minute=0)
        with self.assertRaises(TimeSlotInvalidError):
            self.service.create_reservation("ROOM-101", "alice", "Zero Slot", time_pt, time_pt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
