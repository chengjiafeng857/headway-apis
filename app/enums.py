from enum import Enum


class UserRole(str, Enum):
    patient = "patient"
    provider = "provider"
    admin = "admin"


class SlotStatus(str, Enum):
    open = "open"
    booked = "booked"
    cancelled = "cancelled"


class AppointmentStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    declined = "declined"
    cancelled = "cancelled"
    completed = "completed"


class NotificationType(str, Enum):
    slot_opened = "slot_opened"
    slot_reopened = "slot_reopened"
    appointment_cancelled = "appointment_cancelled"
    appointment_declined = "appointment_declined"


class OutboxStatus(str, Enum):
    pending = "pending"
    published = "published"
    failed = "failed"  # transient failure, still within the retry budget
    dead = "dead"  # exhausted retries; terminal, never re-attempted
