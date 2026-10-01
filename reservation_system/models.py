"""Domain models and exceptions for Meeting Room Reservation System."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional
import uuid


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    CANCELLED_BY_MAINTENANCE = "CANCELLED_BY_MAINTENANCE"
    COMPLETED = "COMPLETED"


class RecurrenceFrequency(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class RecurrencePolicy(str, Enum):
    ALL_OR_NOTHING = "ALL_OR_NOTHING"
    ALLOW_PARTIAL = "ALLOW_PARTIAL"


class MaintenanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --- Exceptions ---

class ReservationSystemError(Exception):
    """Base exception for all reservation system errors."""
    pass


class RoomNotFoundError(ReservationSystemError):
    """Raised when room does not exist."""
    pass


class ReservationNotFoundError(ReservationSystemError):
    """Raised when reservation does not exist."""
    pass


class TimeSlotInvalidError(ReservationSystemError):
    """Raised when start time is not strictly before end time or other slot invalidity."""
    pass


class TimeOverlapError(ReservationSystemError):
    """Raised when two reservations have direct intersecting time slots."""
    def __init__(self, message: str, conflicting_id: Optional[str] = None):
        super().__init__(message)
        self.conflicting_id = conflicting_id


class BufferTimeViolationError(ReservationSystemError):
    """Raised when two reservations do not maintain required transition buffer gap."""
    def __init__(self, message: str, conflicting_id: Optional[str] = None, required_buffer: int = 0):
        super().__init__(message)
        self.conflicting_id = conflicting_id
        self.required_buffer = required_buffer


class MaintenanceConflictError(ReservationSystemError):
    """Raised when a reservation conflicts with a scheduled room maintenance window."""
    def __init__(self, message: str, maintenance_id: Optional[str] = None, affected_reservation_ids: Optional[List[str]] = None):
        super().__init__(message)
        self.maintenance_id = maintenance_id
        self.affected_reservation_ids = affected_reservation_ids or []


class RecurrenceConflictError(ReservationSystemError):
    """Raised when one or more occurrences in a recurring series conflict under ALL_OR_NOTHING."""
    def __init__(self, message: str, failed_instances: Optional[List[dict]] = None):
        super().__init__(message)
        self.failed_instances = failed_instances or []


class InvalidStateTransitionError(ReservationSystemError):
    """Raised when attempting an illegal reservation or maintenance state transition."""
    pass


# --- Domain Entities ---

@dataclass
class TimeSlot:
    """Represents a continuous half-open interval [start_time, end_time)."""
    start_time: datetime
    end_time: datetime

    def __post_init__(self):
        if self.start_time >= self.end_time:
            raise TimeSlotInvalidError(
                f"Start time ({self.start_time.isoformat()}) must be strictly earlier than end time ({self.end_time.isoformat()})"
            )

    @property
    def duration_minutes(self) -> float:
        return (self.end_time - self.start_time).total_seconds() / 60.0

    def direct_overlaps(self, other: TimeSlot) -> bool:
        """Check if two time slots intersect directly: max(start) < min(end)."""
        return self.start_time < other.end_time and other.start_time < self.end_time

    def conflicts_with_buffer(self, other: TimeSlot, buffer_minutes: int) -> bool:
        """
        Check if two reservations conflict considering transition buffer gap B.
        Two reservations [S1, E1) and [S2, E2) violate buffer time if:
        S1 < E2 + B and S2 < E1 + B.
        Equivalently, if S2 >= E1, they require (S2 - E1) >= B.
        """
        buf = timedelta(minutes=buffer_minutes)
        return self.start_time < (other.end_time + buf) and other.start_time < (self.end_time + buf)


@dataclass
class Room:
    """Meeting Room entity."""
    room_id: str
    name: str
    capacity: int
    buffer_minutes: int = 15
    is_active: bool = True
    location: str = ""
    equipment: List[str] = field(default_factory=list)


@dataclass
class RecurrenceRule:
    """Defines recurrence configuration for repeating meetings."""
    frequency: RecurrenceFrequency
    interval: int = 1
    count: Optional[int] = None
    until: Optional[datetime] = None
    policy: RecurrencePolicy = RecurrencePolicy.ALL_OR_NOTHING

    def __post_init__(self):
        if self.interval < 1:
            raise ValueError("Recurrence interval must be >= 1")
        if self.count is None and self.until is None:
            raise ValueError("Either count or until date must be provided for recurrence rule")
        if self.count is not None and self.count < 1:
            raise ValueError("Recurrence count must be >= 1")


@dataclass
class Reservation:
    """Reservation record."""
    reservation_id: str
    room_id: str
    organizer_id: str
    title: str
    start_time: datetime
    end_time: datetime
    buffer_minutes: int = 15
    status: ReservationStatus = ReservationStatus.CONFIRMED
    created_at: datetime = field(default_factory=datetime.now)
    recurrence_id: Optional[str] = None
    recurrence_index: Optional[int] = None
    cancellation_reason: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[str] = None
    notes: str = ""

    @property
    def time_slot(self) -> TimeSlot:
        return TimeSlot(self.start_time, self.end_time)

    @property
    def is_active(self) -> bool:
        """Active reservations block the room schedule."""
        return self.status in (ReservationStatus.CONFIRMED, ReservationStatus.PENDING)


@dataclass
class MaintenanceWindow:
    """Temporary maintenance or cleaning lockout period."""
    maintenance_id: str
    room_id: str
    title: str
    start_time: datetime
    end_time: datetime
    reason: str
    created_by: str
    status: MaintenanceStatus = MaintenanceStatus.SCHEDULED
    created_at: datetime = field(default_factory=datetime.now)
    enforce_buffer: bool = True

    @property
    def time_slot(self) -> TimeSlot:
        return TimeSlot(self.start_time, self.end_time)

    @property
    def is_active(self) -> bool:
        """Active maintenance windows block room reservations."""
        return self.status in (MaintenanceStatus.SCHEDULED, MaintenanceStatus.IN_PROGRESS)
