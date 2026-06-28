from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.enums import AppointmentStatus, NotificationType, UserRole


class UserCreate(BaseModel):
    # Public self-registration always creates a patient. Provider and admin
    # accounts must be provisioned through a trusted/admin path, never chosen by
    # the caller, otherwise anyone could grant themselves elevated privileges.
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class InsurancePlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    carrier_name: str
    plan_name: str
    display_name: str


class ProviderSummary(BaseModel):
    id: int
    display_name: str
    city: str
    state: str
    offers_virtual: bool
    offers_in_person: bool
    specialties: list[str]
    insurance_plans: list[InsurancePlanRead]


class ProviderDetail(ProviderSummary):
    bio: str
    timezone: str


class AvailabilitySlotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: int
    start_at: datetime
    end_at: datetime
    status: str


class AppointmentCreate(BaseModel):
    provider_id: int
    slot_id: int
    reason: str | None = Field(default=None, max_length=1000)


class AppointmentStatusUpdate(BaseModel):
    status: AppointmentStatus
    reason: str | None = Field(default=None, max_length=1000)


class AppointmentCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    provider_id: int
    slot_id: int
    status: AppointmentStatus
    reason: str | None
    cancelled_reason: str | None
    created_at: datetime
    updated_at: datetime


class SlotWatcherCreate(BaseModel):
    provider_id: int
    start_after: datetime
    start_before: datetime

    @field_validator("start_after", "start_before")
    @classmethod
    def normalize_to_utc(cls, value: datetime) -> datetime:
        # Treat naive datetimes as UTC and normalize everything to UTC so the
        # watcher window is compared consistently against stored slot times.
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_window(self) -> "SlotWatcherCreate":
        if self.start_before <= self.start_after:
            raise ValueError("start_before must be after start_after")
        if self.start_before <= datetime.now(UTC):
            raise ValueError("start_before must be in the future")
        return self


class SlotWatcherRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    provider_id: int
    start_after: datetime
    start_before: datetime
    is_active: bool


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    slot_id: int
    appointment_request_id: int
    type: NotificationType
    message: str
    is_read: bool
    created_at: datetime
    read_at: datetime | None
