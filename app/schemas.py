from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.enums import AppointmentStatus, NotificationType, UserRole


AddressSource = Literal["self_reported", "insurance", "provider", "imported"]


def trim_optional_text(value: str | None) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def normalize_text_list(value: list[str] | str | None) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, str)):
        raise ValueError("value must be a string or list of strings")
    raw_items = [value] if isinstance(value, str) else value
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, str):
            raise ValueError("all list items must be strings")
        stripped = item.strip()
        if not stripped:
            continue
        key = stripped.lower()
        if key not in seen:
            normalized.append(stripped)
            seen.add(key)
    return normalized


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserCreate(RequestModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)
    role: UserRole

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("role")
    @classmethod
    def disallow_public_admin_registration(cls, value: UserRole) -> UserRole:
        if value == UserRole.admin:
            raise ValueError("admin users cannot self-register")
        return value


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool


class LoginRequest(RequestModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower() if isinstance(value, str) else value


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class InsurancePlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    carrier_name: str
    plan_name: str
    display_name: str


class ProviderBrief(BaseModel):
    # Lightweight provider identity for embedding in other responses (follows,
    # availability), where the full ProviderSummary would be unnecessarily heavy.
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    provider_type: str
    credential: str | None
    profile_photo_url: str | None
    city: str
    state: str


class ProviderSummary(BaseModel):
    id: int
    display_name: str
    provider_type: str
    credential: str | None
    profile_photo_url: str | None
    quote: str
    city: str
    state: str
    years_experience: int | None
    gender: str | None
    ethnicity: str | None
    languages: list[str]
    license_states: list[str]
    offers_virtual: bool
    offers_in_person: bool
    offers_free_consultation: bool
    accepting_new_clients: bool
    next_available_at: datetime | None
    specialties: list[str]
    style_tags: list[str]
    care_types: list[str]
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


class ProviderSlotRead(AvailabilitySlotRead):
    # Provider-facing view of their own slots. The appointment_id / patient_* fields
    # are set only for booked slots (the active appointment + the patient holding
    # it); all None for open/cancelled slots.
    appointment_id: int | None = None
    patient_id: int | None = None
    patient_name: str | None = None
    patient_email: EmailStr | None = None


class ProviderAvailabilityRead(BaseModel):
    # Open slots for a provider, plus enough provider identity for the client to
    # render the availability view without a second /providers/{id} call.
    provider: ProviderBrief
    slots: list[AvailabilitySlotRead]


class ProviderProfileCreate(RequestModel):
    display_name: str = Field(min_length=1, max_length=120)
    provider_type: str = Field(default="therapist", min_length=1, max_length=80)
    credential: str | None = Field(default=None, max_length=80)
    profile_photo_url: str | None = Field(default=None, max_length=500)
    quote: str = Field(default="", max_length=500)
    bio: str = Field(default="", max_length=2000)
    city: str = Field(min_length=1, max_length=80)
    state: str = Field(min_length=1, max_length=40)
    timezone: str = Field(default="America/New_York", min_length=1, max_length=80)
    years_experience: int | None = Field(default=None, ge=0, le=80)
    gender: str | None = Field(default=None, max_length=80)
    ethnicity: str | None = Field(default=None, max_length=120)
    languages: list[str] = Field(default_factory=list, max_length=20)
    license_states: list[str] = Field(default_factory=list, max_length=20)
    offers_virtual: bool = True
    offers_in_person: bool = False
    offers_free_consultation: bool = False
    accepting_new_clients: bool = True

    @field_validator(
        "display_name",
        "provider_type",
        "credential",
        "profile_photo_url",
        "quote",
        "bio",
        "city",
        "state",
        "timezone",
        "gender",
        "ethnicity",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return trim_optional_text(value)

    @field_validator("languages", "license_states", mode="before")
    @classmethod
    def normalize_lists(cls, value: list[str] | str | None) -> list[str]:
        return normalize_text_list(value)

    @model_validator(mode="after")
    def validate_care_type(self) -> "ProviderProfileCreate":
        if not self.offers_virtual and not self.offers_in_person:
            raise ValueError("at least one care type must be offered")
        return self


class ProviderProfileUpdate(RequestModel):
    # All optional: PATCH applies only the fields the caller actually sends.
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    provider_type: str | None = Field(default=None, min_length=1, max_length=80)
    credential: str | None = Field(default=None, max_length=80)
    profile_photo_url: str | None = Field(default=None, max_length=500)
    quote: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=2000)
    city: str | None = Field(default=None, min_length=1, max_length=80)
    state: str | None = Field(default=None, min_length=1, max_length=40)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    years_experience: int | None = Field(default=None, ge=0, le=80)
    gender: str | None = Field(default=None, max_length=80)
    ethnicity: str | None = Field(default=None, max_length=120)
    languages: list[str] | None = Field(default=None, max_length=20)
    license_states: list[str] | None = Field(default=None, max_length=20)
    offers_virtual: bool | None = None
    offers_in_person: bool | None = None
    offers_free_consultation: bool | None = None
    accepting_new_clients: bool | None = None

    @field_validator(
        "display_name",
        "provider_type",
        "credential",
        "profile_photo_url",
        "quote",
        "bio",
        "city",
        "state",
        "timezone",
        "gender",
        "ethnicity",
        mode="before",
    )
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        return trim_optional_text(value)

    @field_validator("languages", "license_states", mode="before")
    @classmethod
    def normalize_optional_lists(cls, value: list[str] | str | None) -> list[str] | None:
        return None if value is None else normalize_text_list(value)


class AvailabilitySlotCreate(RequestModel):
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def normalize_to_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_window(self) -> "AvailabilitySlotCreate":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        if self.start_at <= datetime.now(UTC):
            raise ValueError("start_at must be in the future")
        return self


class ProviderSpecialtiesUpdate(RequestModel):
    specialty_ids: list[int] = Field(default_factory=list)


class ProviderInsurancePlansUpdate(RequestModel):
    insurance_plan_ids: list[int] = Field(default_factory=list)


class ProviderStyleTagsUpdate(RequestModel):
    style_tag_ids: list[int] = Field(default_factory=list)


class ProviderCareTypesUpdate(RequestModel):
    care_type_ids: list[int] = Field(default_factory=list)


class PatientProfileCreate(RequestModel):
    preferred_name: str | None = Field(default=None, max_length=120)
    legal_name: str | None = Field(default=None, max_length=120)
    pronouns: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=40)
    gender: str | None = Field(default=None, max_length=80)
    gender_status: str | None = Field(default=None, max_length=80)
    ethnicity: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=80)
    insurance_plan_id: int | None = Field(default=None, gt=0)
    two_factor_enrolled: bool | None = None

    @field_validator(
        "preferred_name",
        "legal_name",
        "pronouns",
        "phone",
        "gender",
        "gender_status",
        "ethnicity",
        "language",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return trim_optional_text(value)


class PatientProfileUpdate(PatientProfileCreate):
    pass


class PatientProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    preferred_name: str | None
    legal_name: str | None
    pronouns: str | None
    phone: str | None
    gender: str | None
    gender_status: str | None
    ethnicity: str | None
    language: str | None
    insurance_plan_id: int | None
    # Resolved plan details (carrier / plan / display name), so a patient profile
    # can show its insurance the same way provider profiles do — not just an id.
    insurance_plan: InsurancePlanRead | None = None
    two_factor_enrolled: bool
    created_at: datetime
    updated_at: datetime


class PatientAddressCreate(RequestModel):
    label: str = Field(default="home", min_length=1, max_length=40)
    line1: str = Field(min_length=1, max_length=160)
    line2: str | None = Field(default=None, max_length=160)
    city: str = Field(min_length=1, max_length=80)
    state: str = Field(min_length=1, max_length=40)
    postal_code: str = Field(min_length=1, max_length=20)
    country: str = Field(default="US", min_length=2, max_length=2)
    source: AddressSource = "self_reported"
    is_primary: bool = False

    @field_validator("label", "line1", "line2", "city", "state", "postal_code", mode="before")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return trim_optional_text(value)

    @field_validator("country", mode="before")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.strip().upper() if isinstance(value, str) else value


class PatientAddressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    label: str
    line1: str
    line2: str | None
    city: str
    state: str
    postal_code: str
    country: str
    source: AddressSource
    is_primary: bool
    created_at: datetime
    updated_at: datetime


class EmergencyContactWrite(RequestModel):
    full_name: str = Field(min_length=1, max_length=120)
    relationship: str | None = Field(default=None, max_length=80)
    phone: str = Field(min_length=1, max_length=40)
    email: EmailStr | None = None
    priority: int | None = Field(default=None, ge=1, le=2)
    permission_to_contact: bool = True

    @field_validator("full_name", "relationship", "phone", mode="before")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return trim_optional_text(value)


class EmergencyContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    full_name: str
    relationship: str | None
    phone: str
    email: EmailStr | None
    priority: int
    permission_to_contact: bool
    created_at: datetime
    updated_at: datetime


class ConsentFormRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    form_key: str
    title: str
    version: str
    body_url: str | None
    is_required: bool
    is_active: bool


class PatientConsentRead(BaseModel):
    form_key: str
    title: str
    version: str
    body_url: str | None
    is_required: bool
    accepted: bool
    accepted_at: datetime | None
    revoked_at: datetime | None


class PatientAccountRead(BaseModel):
    profile: PatientProfileRead | None
    addresses: list[PatientAddressRead]
    emergency_contacts: list[EmergencyContactRead]
    consents: list[PatientConsentRead]


class AppointmentCreate(RequestModel):
    provider_id: int = Field(gt=0)
    slot_id: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=1000)


class AppointmentStatusUpdate(RequestModel):
    status: AppointmentStatus
    reason: str | None = Field(default=None, max_length=1000)


class AppointmentCancel(RequestModel):
    reason: str | None = Field(default=None, max_length=1000)


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    provider_id: int
    # Flat provider identity (read from AppointmentRequest properties), so clients
    # don't need a second /providers/{id} call to label an appointment.
    provider_name: str
    provider_type: str
    slot_id: int
    status: AppointmentStatus
    reason: str | None
    cancelled_reason: str | None
    created_at: datetime
    updated_at: datetime


class SlotWatcherCreate(RequestModel):
    provider_id: int = Field(gt=0)
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


class ProviderFollowCreate(RequestModel):
    provider_id: int = Field(gt=0)


class ProviderFollowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    provider_id: int
    is_active: bool
    created_at: datetime
    provider: ProviderBrief


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    slot_id: int
    provider_id: int
    provider_name: str
    start_at: datetime
    end_at: datetime
    appointment_request_id: int | None
    type: NotificationType
    message: str
    is_read: bool
    created_at: datetime
    read_at: datetime | None
