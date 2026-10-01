"""High-level Reservation Management Service."""

from __future__ import annotations
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple, Union
import uuid

from .models import (
    Room,
    Reservation,
    TimeSlot,
    MaintenanceWindow,
    ReservationStatus,
    MaintenanceStatus,
    RecurrenceRule,
    RecurrencePolicy,
    RoomNotFoundError,
    ReservationNotFoundError,
    TimeSlotInvalidError,
    TimeOverlapError,
    BufferTimeViolationError,
    MaintenanceConflictError,
    RecurrenceConflictError,
    InvalidStateTransitionError,
)
from .conflict_checker import ConflictChecker
from .recurrence_service import RecurrenceService


class ReservationService:
    """Core domain service for meeting room bookings, buffers, recurrence, maintenance, and cancellations."""

    def __init__(self):
        self._rooms: Dict[str, Room] = {}
        self._reservations: Dict[str, Reservation] = {}
        self._maintenances: Dict[str, MaintenanceWindow] = {}

    # --- Room Management ---

    def add_room(self, room: Room) -> Room:
        self._rooms[room.room_id] = room
        return room

    def get_room(self, room_id: str) -> Room:
        if room_id not in self._rooms:
            raise RoomNotFoundError(f"Room with ID '{room_id}' does not exist.")
        return self._rooms[room_id]

    def list_rooms(self) -> List[Room]:
        return list(self._rooms.values())

    # --- Reservation Queries ---

    def get_reservation(self, reservation_id: str) -> Reservation:
        if reservation_id not in self._reservations:
            raise ReservationNotFoundError(f"Reservation with ID '{reservation_id}' does not exist.")
        return self._reservations[reservation_id]

    def list_reservations_for_room(self, room_id: str, active_only: bool = False) -> List[Reservation]:
        res_list = [r for r in self._reservations.values() if r.room_id == room_id]
        if active_only:
            res_list = [r for r in res_list if r.is_active]
        return sorted(res_list, key=lambda r: r.start_time)

    def list_maintenances_for_room(self, room_id: str, active_only: bool = False) -> List[MaintenanceWindow]:
        m_list = [m for m in self._maintenances.values() if m.room_id == room_id]
        if active_only:
            m_list = [m for m in m_list if m.is_active]
        return sorted(m_list, key=lambda m: m.start_time)

    # --- Rule 1, 2, 3: Create Reservation (Single or Recurring) ---

    def create_reservation(
        self,
        room_id: str,
        organizer_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        buffer_minutes: Optional[int] = None,
        recurrence_rule: Optional[RecurrenceRule] = None,
        notes: str = "",
    ) -> Union[Reservation, Tuple[List[Reservation], List[dict]]]:
        """
        Creates a single or recurring reservation.
        Enforces:
        - Rule 1: Time Overlap Prevention
        - Rule 2: Buffer Time Gap
        - Rule 3: Recurring Series Conflict Validation
        - Rule 4: Maintenance Lockout Check
        """
        room = self.get_room(room_id)
        if not room.is_active:
            raise RoomNotFoundError(f"Room '{room.name}' ({room_id}) is deactivated.")

        base_slot = TimeSlot(start_time, end_time)
        effective_buffer = buffer_minutes if buffer_minutes is not None else room.buffer_minutes

        active_res = self.list_reservations_for_room(room_id, active_only=True)
        active_maint = self.list_maintenances_for_room(room_id, active_only=True)

        # Single Reservation Case
        if recurrence_rule is None:
            # Conflict check raises TimeOverlapError, BufferTimeViolationError, or MaintenanceConflictError
            ConflictChecker.check_conflict(
                candidate_slot=base_slot,
                active_reservations=active_res,
                active_maintenances=active_maint,
                buffer_minutes=effective_buffer,
            )

            reservation_id = f"RES-{uuid.uuid4().hex[:8].upper()}"
            res = Reservation(
                reservation_id=reservation_id,
                room_id=room_id,
                organizer_id=organizer_id,
                title=title,
                start_time=start_time,
                end_time=end_time,
                buffer_minutes=effective_buffer,
                status=ReservationStatus.CONFIRMED,
                notes=notes,
            )
            self._reservations[reservation_id] = res
            return res

        # Recurring Meeting Case
        series_id = f"SERIES-{uuid.uuid4().hex[:8].upper()}"
        valid_slots, conflicts_report = RecurrenceService.evaluate_series(
            base_slot=base_slot,
            rule=recurrence_rule,
            active_reservations=active_res,
            active_maintenances=active_maint,
            buffer_minutes=effective_buffer,
        )

        created_reservations: List[Reservation] = []
        for idx, slot in valid_slots:
            res_id = f"RES-{uuid.uuid4().hex[:8].upper()}"
            res = Reservation(
                reservation_id=res_id,
                room_id=room_id,
                organizer_id=organizer_id,
                title=f"{title} (#{idx + 1})",
                start_time=slot.start_time,
                end_time=slot.end_time,
                buffer_minutes=effective_buffer,
                status=ReservationStatus.CONFIRMED,
                recurrence_id=series_id,
                recurrence_index=idx,
                notes=notes,
            )
            self._reservations[res_id] = res
            created_reservations.append(res)

        return created_reservations, conflicts_report

    # --- Rule 5: Reservation Cancellation & Slot Release ---

    def cancel_reservation(
        self,
        reservation_id: str,
        cancelled_by: str,
        reason: str = "User requested cancellation",
    ) -> Reservation:
        """
        Cancels an active reservation, transitioning its state to CANCELLED
        and immediately releasing the time slot and buffer back to available status.
        """
        res = self.get_reservation(reservation_id)

        if res.status in (ReservationStatus.CANCELLED, ReservationStatus.CANCELLED_BY_MAINTENANCE):
            raise InvalidStateTransitionError(
                f"Reservation {reservation_id} is already cancelled (status: {res.status})."
            )
        if res.status == ReservationStatus.COMPLETED:
            raise InvalidStateTransitionError(
                f"Cannot cancel completed reservation {reservation_id}."
            )

        res.status = ReservationStatus.CANCELLED
        res.cancelled_at = datetime.now()
        res.cancelled_by = cancelled_by
        res.cancellation_reason = reason
        return res

    def cancel_recurring_series(
        self,
        recurrence_id: str,
        cancelled_by: str,
        reason: str = "Series cancelled by organizer",
    ) -> List[Reservation]:
        """Cancels all active reservations belonging to a recurring series."""
        series_res = [
            r for r in self._reservations.values()
            if r.recurrence_id == recurrence_id and r.is_active
        ]
        cancelled = []
        for r in series_res:
            self.cancel_reservation(r.reservation_id, cancelled_by=cancelled_by, reason=reason)
            cancelled.append(r)
        return cancelled

    # --- Rule 4: Temporary Maintenance & Override ---

    def schedule_maintenance(
        self,
        room_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        reason: str,
        admin_id: str,
        override_affected: bool = False,
        enforce_buffer: bool = True,
    ) -> Tuple[MaintenanceWindow, List[Reservation]]:
        """
        Locks out room during maintenance window.
        If active bookings conflict:
        - If override_affected is False: raises MaintenanceConflictError.
        - If override_affected is True: forcibly cancels affected bookings with CANCELLED_BY_MAINTENANCE.
        """
        room = self.get_room(room_id)
        maint_slot = TimeSlot(start_time, end_time)

        # Check existing active reservations for overlap
        active_res = self.list_reservations_for_room(room_id, active_only=True)
        conflicting_reservations: List[Reservation] = []

        for res in active_res:
            # Overlap check or buffer-encroach check
            has_conflict = maint_slot.direct_overlaps(res.time_slot)
            if not has_conflict and enforce_buffer:
                has_conflict = maint_slot.conflicts_with_buffer(res.time_slot, room.buffer_minutes)

            if has_conflict:
                conflicting_reservations.append(res)

        if conflicting_reservations and not override_affected:
            conf_ids = [r.reservation_id for r in conflicting_reservations]
            raise MaintenanceConflictError(
                f"Cannot schedule maintenance '{title}': room has {len(conflicting_reservations)} "
                f"active reservation(s) during this window. Use override_affected=True to override.",
                affected_reservation_ids=conf_ids,
            )

        # Evict / override affected reservations if allowed
        evicted_reservations: List[Reservation] = []
        for res in conflicting_reservations:
            res.status = ReservationStatus.CANCELLED_BY_MAINTENANCE
            res.cancelled_at = datetime.now()
            res.cancelled_by = admin_id
            res.cancellation_reason = f"Room maintenance override: {title} ({reason})"
            evicted_reservations.append(res)

        maint_id = f"MAINT-{uuid.uuid4().hex[:8].upper()}"
        maint = MaintenanceWindow(
            maintenance_id=maint_id,
            room_id=room_id,
            title=title,
            start_time=start_time,
            end_time=end_time,
            reason=reason,
            created_by=admin_id,
            status=MaintenanceStatus.SCHEDULED,
            enforce_buffer=enforce_buffer,
        )
        self._maintenances[maint_id] = maint
        return maint, evicted_reservations

    def cancel_maintenance(self, maintenance_id: str, admin_id: str) -> MaintenanceWindow:
        """Cancels a maintenance window and frees the room."""
        if maintenance_id not in self._maintenances:
            raise ReservationSystemError(f"Maintenance window '{maintenance_id}' not found.")
        maint = self._maintenances[maintenance_id]
        if maint.status in (MaintenanceStatus.CANCELLED, MaintenanceStatus.COMPLETED):
            raise InvalidStateTransitionError(f"Maintenance window is already {maint.status}.")
        maint.status = MaintenanceStatus.CANCELLED
        return maint
