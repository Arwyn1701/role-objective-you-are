"""Conflict detection engine for Time Overlap, Buffer Time, and Maintenance Windows."""

from __future__ import annotations
from typing import List, Optional, Tuple
from datetime import datetime

from .models import (
    TimeSlot,
    Reservation,
    MaintenanceWindow,
    TimeOverlapError,
    BufferTimeViolationError,
    MaintenanceConflictError,
)


class ConflictChecker:
    """Evaluates time slot feasibility against reservations and maintenance blackouts."""

    @staticmethod
    def check_conflict(
        candidate_slot: TimeSlot,
        active_reservations: List[Reservation],
        active_maintenances: List[MaintenanceWindow],
        buffer_minutes: int,
        ignore_reservation_id: Optional[str] = None,
    ) -> None:
        """
        Validates if candidate_slot is free from:
        1. Maintenance conflicts
        2. Direct time overlaps with existing reservations
        3. Buffer time violations with existing reservations

        Raises specific exceptions if conflicts are found.
        """
        # 1. Check Maintenance Windows first
        for maint in active_maintenances:
            if not maint.is_active:
                continue
            
            # Direct overlap with maintenance window
            if candidate_slot.direct_overlaps(maint.time_slot):
                raise MaintenanceConflictError(
                    f"Room is unavailable due to scheduled maintenance '{maint.title}' "
                    f"from {maint.start_time.isoformat()} to {maint.end_time.isoformat()} "
                    f"(Reason: {maint.reason}).",
                    maintenance_id=maint.maintenance_id,
                )
            
            # Buffer check around maintenance if enforced
            if maint.enforce_buffer and candidate_slot.conflicts_with_buffer(maint.time_slot, buffer_minutes):
                raise MaintenanceConflictError(
                    f"Reservation encroaches on buffer window for maintenance '{maint.title}' "
                    f"[{maint.start_time.isoformat()} - {maint.end_time.isoformat()}]. "
                    f"Required gap: {buffer_minutes}m.",
                    maintenance_id=maint.maintenance_id,
                )

        # 2. Check Active Reservations
        for res in active_reservations:
            if not res.is_active:
                continue
            if ignore_reservation_id and res.reservation_id == ignore_reservation_id:
                continue

            # (A) Condition 1: Direct Time Overlap
            if candidate_slot.direct_overlaps(res.time_slot):
                raise TimeOverlapError(
                    f"Direct time overlap with existing reservation '{res.title}' "
                    f"[{res.start_time.isoformat()} - {res.end_time.isoformat()}].",
                    conflicting_id=res.reservation_id,
                )

            # (B) Condition 2: Buffer Time Gap
            # Use maximum of room buffer or reservation buffer
            effective_buffer = max(buffer_minutes, res.buffer_minutes)
            if candidate_slot.conflicts_with_buffer(res.time_slot, effective_buffer):
                # Calculate actual gap between the two intervals
                if candidate_slot.end_time <= res.start_time:
                    gap_mins = (res.start_time - candidate_slot.end_time).total_seconds() / 60.0
                    rel_msg = f"only {gap_mins:.0f}m gap before next meeting"
                else:
                    gap_mins = (candidate_slot.start_time - res.end_time).total_seconds() / 60.0
                    rel_msg = f"only {gap_mins:.0f}m gap after previous meeting"

                raise BufferTimeViolationError(
                    f"Buffer time violation with reservation '{res.title}' "
                    f"[{res.start_time.isoformat()} - {res.end_time.isoformat()}]. "
                    f"Mandatory buffer is {effective_buffer}m, but found {rel_msg}.",
                    conflicting_id=res.reservation_id,
                    required_buffer=effective_buffer,
                )

    @staticmethod
    def inspect_conflicts(
        candidate_slot: TimeSlot,
        active_reservations: List[Reservation],
        active_maintenances: List[MaintenanceWindow],
        buffer_minutes: int,
        ignore_reservation_id: Optional[str] = None,
    ) -> List[Tuple[str, str, Optional[str]]]:
        """
        Non-raising inspection returning a list of conflict tuples:
        (conflict_type, message, reference_id)
        Useful for UI preview and batch analysis.
        """
        conflicts = []
        try:
            ConflictChecker.check_conflict(
                candidate_slot=candidate_slot,
                active_reservations=active_reservations,
                active_maintenances=active_maintenances,
                buffer_minutes=buffer_minutes,
                ignore_reservation_id=ignore_reservation_id,
            )
        except MaintenanceConflictError as e:
            conflicts.append(("MAINTENANCE", str(e), e.maintenance_id))
        except TimeOverlapError as e:
            conflicts.append(("OVERLAP", str(e), e.conflicting_id))
        except BufferTimeViolationError as e:
            conflicts.append(("BUFFER", str(e), e.conflicting_id))
        return conflicts
