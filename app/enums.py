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
    slot_reopened = "slot_reopened"
