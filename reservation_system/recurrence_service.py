"""Recurrence expansion and conflict validation engine."""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import calendar

from .models import (
    TimeSlot,
    RecurrenceRule,
    RecurrenceFrequency,
    RecurrencePolicy,
    Reservation,
    MaintenanceWindow,
    RecurrenceConflictError,
    ReservationSystemError,
)
from .conflict_checker import ConflictChecker


class RecurrenceService:
    """Handles recurring meeting rule evaluation and occurrence generation."""

    @staticmethod
    def _add_month(dt: datetime, months: int = 1) -> datetime:
        """Add months safely preserving day of month when possible."""
        year = dt.year + (dt.month + months - 1) // 12
        month = (dt.month + months - 1) % 12 + 1
        max_day = calendar.monthrange(year, month)[1]
        day = min(dt.day, max_day)
        return dt.replace(year=year, month=month, day=day)

    @classmethod
    def generate_slots(
        cls,
        base_slot: TimeSlot,
        rule: RecurrenceRule,
    ) -> List[Tuple[int, TimeSlot]]:
        """
        Expands the recurrence rule into concrete (index, TimeSlot) tuples.
        """
        slots: List[Tuple[int, TimeSlot]] = []
        duration = base_slot.end_time - base_slot.start_time
        curr_start = base_slot.start_time
        index = 0

        while True:
            # Check count condition
            if rule.count is not None and index >= rule.count:
                break
            # Check until date condition
            if rule.until is not None and curr_start > rule.until:
                break

            curr_end = curr_start + duration
            slots.append((index, TimeSlot(curr_start, curr_end)))
            index += 1

            # Advance to next occurrence
            if rule.frequency == RecurrenceFrequency.DAILY:
                curr_start = curr_start + timedelta(days=rule.interval)
            elif rule.frequency == RecurrenceFrequency.WEEKLY:
                curr_start = curr_start + timedelta(weeks=rule.interval)
            elif rule.frequency == RecurrenceFrequency.BIWEEKLY:
                curr_start = curr_start + timedelta(weeks=2 * rule.interval)
            elif rule.frequency == RecurrenceFrequency.MONTHLY:
                curr_start = cls._add_month(curr_start, rule.interval)
            else:
                raise ValueError(f"Unsupported recurrence frequency: {rule.frequency}")

        return slots

    @classmethod
    def evaluate_series(
        cls,
        base_slot: TimeSlot,
        rule: RecurrenceRule,
        active_reservations: List[Reservation],
        active_maintenances: List[MaintenanceWindow],
        buffer_minutes: int,
    ) -> Tuple[List[Tuple[int, TimeSlot]], List[dict]]:
        """
        Validates all occurrences against room schedule.
        Returns:
            (valid_slots, conflicts_report)
        If policy is ALL_OR_NOTHING and any conflict exists, raises RecurrenceConflictError.
        """
        candidate_instances = cls.generate_slots(base_slot, rule)
        valid_slots: List[Tuple[int, TimeSlot]] = []
        conflicts_report: List[dict] = []

        # We will also keep track of new slots booked in this series so they don't self-conflict
        simulated_reservations = list(active_reservations)

        for idx, slot in candidate_instances:
            conflict_items = ConflictChecker.inspect_conflicts(
                candidate_slot=slot,
                active_reservations=simulated_reservations,
                active_maintenances=active_maintenances,
                buffer_minutes=buffer_minutes,
            )

            if conflict_items:
                for ctype, cmsg, ref_id in conflict_items:
                    conflicts_report.append({
                        "index": idx,
                        "slot": (slot.start_time.isoformat(), slot.end_time.isoformat()),
                        "conflict_type": ctype,
                        "message": cmsg,
                        "reference_id": ref_id,
                    })
            else:
                valid_slots.append((idx, slot))
                # Add temporary stub so later occurrences can verify gap if needed
                # (Though standard daily/weekly meetings have gaps > buffer)

        if conflicts_report and rule.policy == RecurrencePolicy.ALL_OR_NOTHING:
            raise RecurrenceConflictError(
                f"Recurring series validation failed: {len(conflicts_report)} of {len(candidate_instances)} "
                f"occurrences have conflicts under ALL_OR_NOTHING policy.",
                failed_instances=conflicts_report,
            )

        return valid_slots, conflicts_report
