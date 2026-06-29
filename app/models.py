from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm import relationship as orm_relationship

from app.core.database import Base
from app.enums import AppointmentStatus, NotificationType, OutboxStatus, SlotStatus, UserRole


def enum_values(enum_class: type) -> str:
    return ", ".join(f"'{item.value}'" for item in enum_class)


class User(Base):
    __tablename__ = "app_users"
    __table_args__ = (
        CheckConstraint(f"role IN ({enum_values(UserRole)})", name="ck_app_users_role"),
        Index("ix_app_users_email", "email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=UserRole.patient.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    provider_profile: Mapped["ProviderProfile | None"] = relationship(back_populates="user")
    patient_profile: Mapped["PatientProfile | None"] = relationship(back_populates="user")
    patient_addresses: Mapped[list["PatientAddress"]] = relationship(back_populates="patient")
    emergency_contacts: Mapped[list["EmergencyContact"]] = relationship(back_populates="patient")
    consent_acknowledgements: Mapped[list["PatientConsentAcknowledgement"]] = relationship(
        back_populates="patient"
    )
    appointments: Mapped[list["AppointmentRequest"]] = relationship(
        back_populates="patient", foreign_keys="AppointmentRequest.patient_id"
    )
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user")
    provider_follows: Mapped[list["ProviderFollow"]] = relationship(back_populates="patient")


class PatientProfile(Base):
    __tablename__ = "patient_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_patient_profiles_user_id"),
        Index("ix_patient_profiles_insurance_plan", "insurance_plan_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(String(120))
    legal_name: Mapped[str | None] = mapped_column(String(120))
    pronouns: Mapped[str | None] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(40))
    gender: Mapped[str | None] = mapped_column(String(80))
    gender_status: Mapped[str | None] = mapped_column(String(80))
    ethnicity: Mapped[str | None] = mapped_column(String(120))
    language: Mapped[str | None] = mapped_column(String(80))
    insurance_plan_id: Mapped[int | None] = mapped_column(ForeignKey("insurance_plans.id"))
    two_factor_enrolled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="patient_profile")
    insurance_plan: Mapped["InsurancePlan | None"] = relationship()


class PatientAddress(Base):
    __tablename__ = "patient_addresses"
    __table_args__ = (
        CheckConstraint(
            "source IN ('self_reported', 'insurance', 'provider', 'imported')",
            name="ck_patient_addresses_source",
        ),
        Index("ix_patient_addresses_patient", "patient_id"),
        Index(
            "uq_patient_primary_address",
            "patient_id",
            unique=True,
            postgresql_where=text("is_primary = true"),
            sqlite_where=text("is_primary = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(40), nullable=False, default="home")
    line1: Mapped[str] = mapped_column(String(160), nullable=False)
    line2: Mapped[str | None] = mapped_column(String(160))
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="US")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="self_reported")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    patient: Mapped[User] = relationship(back_populates="patient_addresses")


class EmergencyContact(Base):
    __tablename__ = "emergency_contacts"
    __table_args__ = (
        CheckConstraint("priority BETWEEN 1 AND 2", name="ck_emergency_contacts_priority"),
        UniqueConstraint("patient_id", "priority", name="uq_emergency_contact_priority"),
        Index("ix_emergency_contacts_patient", "patient_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    relationship: Mapped[str | None] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    permission_to_contact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    patient: Mapped[User] = orm_relationship(back_populates="emergency_contacts")


class ConsentForm(Base):
    __tablename__ = "consent_forms"
    __table_args__ = (
        UniqueConstraint("form_key", name="uq_consent_forms_key"),
        Index("ix_consent_forms_active_required", "is_active", "is_required"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    form_key: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    body_url: Mapped[str | None] = mapped_column(String(500))
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    acknowledgements: Mapped[list["PatientConsentAcknowledgement"]] = relationship(
        back_populates="consent_form"
    )


class PatientConsentAcknowledgement(Base):
    __tablename__ = "patient_consent_acknowledgements"
    __table_args__ = (
        UniqueConstraint(
            "patient_id",
            "consent_form_id",
            name="uq_patient_consent_acknowledgement",
        ),
        Index("ix_patient_consents_patient_accepted", "patient_id", "accepted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    consent_form_id: Mapped[int] = mapped_column(ForeignKey("consent_forms.id"), nullable=False)
    form_version: Mapped[str] = mapped_column(String(40), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    patient: Mapped[User] = relationship(back_populates="consent_acknowledgements")
    consent_form: Mapped[ConsentForm] = relationship(back_populates="acknowledgements")


class ProviderProfile(Base):
    __tablename__ = "provider_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_provider_profiles_user_id"),
        Index("ix_provider_profiles_city_state", "city", "state"),
        Index("ix_provider_profiles_offers_virtual", "offers_virtual"),
        Index("ix_provider_profiles_offers_in_person", "offers_in_person"),
        Index("ix_provider_profiles_provider_type", "provider_type"),
        Index("ix_provider_profiles_gender", "gender"),
        Index("ix_provider_profiles_ethnicity", "ethnicity"),
        Index("ix_provider_profiles_accepting", "accepting_new_clients"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(80), nullable=False, default="therapist")
    credential: Mapped[str | None] = mapped_column(String(80))
    profile_photo_url: Mapped[str | None] = mapped_column(String(500))
    quote: Mapped[str] = mapped_column(Text, nullable=False, default="")
    bio: Mapped[str] = mapped_column(Text, nullable=False, default="")
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="America/New_York")
    years_experience: Mapped[int | None] = mapped_column(Integer)
    gender: Mapped[str | None] = mapped_column(String(80))
    ethnicity: Mapped[str | None] = mapped_column(String(120))
    languages: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    license_states: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    offers_virtual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    offers_in_person: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    offers_free_consultation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accepting_new_clients: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="provider_profile")
    specialties: Mapped[list["Specialty"]] = relationship(
        secondary="provider_specialties", back_populates="providers"
    )
    style_tags: Mapped[list["StyleTag"]] = relationship(
        secondary="provider_style_tags", back_populates="providers"
    )
    care_types: Mapped[list["CareType"]] = relationship(
        secondary="provider_care_types", back_populates="providers"
    )
    insurance_plans: Mapped[list["InsurancePlan"]] = relationship(
        secondary="provider_insurance_plans", back_populates="providers"
    )
    availability_slots: Mapped[list["AvailabilitySlot"]] = relationship(back_populates="provider")
    appointments: Mapped[list["AppointmentRequest"]] = relationship(back_populates="provider")
    followers: Mapped[list["ProviderFollow"]] = relationship(back_populates="provider")


class Specialty(Base):
    __tablename__ = "specialties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)

    providers: Mapped[list[ProviderProfile]] = relationship(
        secondary="provider_specialties", back_populates="specialties"
    )


class ProviderSpecialty(Base):
    __tablename__ = "provider_specialties"
    __table_args__ = (Index("ix_provider_specialties_specialty", "specialty_id"),)

    provider_id: Mapped[int] = mapped_column(ForeignKey("provider_profiles.id"), primary_key=True)
    specialty_id: Mapped[int] = mapped_column(ForeignKey("specialties.id"), primary_key=True)


class StyleTag(Base):
    __tablename__ = "style_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)

    providers: Mapped[list[ProviderProfile]] = relationship(
        secondary="provider_style_tags", back_populates="style_tags"
    )


class ProviderStyleTag(Base):
    __tablename__ = "provider_style_tags"
    __table_args__ = (Index("ix_provider_style_tags_style", "style_tag_id"),)

    provider_id: Mapped[int] = mapped_column(ForeignKey("provider_profiles.id"), primary_key=True)
    style_tag_id: Mapped[int] = mapped_column(ForeignKey("style_tags.id"), primary_key=True)


class CareType(Base):
    __tablename__ = "care_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    providers: Mapped[list[ProviderProfile]] = relationship(
        secondary="provider_care_types", back_populates="care_types"
    )


class ProviderCareType(Base):
    __tablename__ = "provider_care_types"
    __table_args__ = (Index("ix_provider_care_types_care", "care_type_id"),)

    provider_id: Mapped[int] = mapped_column(ForeignKey("provider_profiles.id"), primary_key=True)
    care_type_id: Mapped[int] = mapped_column(ForeignKey("care_types.id"), primary_key=True)


class InsurancePlan(Base):
    __tablename__ = "insurance_plans"
    __table_args__ = (
        UniqueConstraint("carrier_name", "plan_name", name="uq_insurance_carrier_plan"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    carrier_name: Mapped[str] = mapped_column(String(100), nullable=False)
    plan_name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)

    providers: Mapped[list[ProviderProfile]] = relationship(
        secondary="provider_insurance_plans", back_populates="insurance_plans"
    )


class ProviderInsurancePlan(Base):
    __tablename__ = "provider_insurance_plans"
    __table_args__ = (Index("ix_provider_insurance_plans_plan", "insurance_plan_id"),)

    provider_id: Mapped[int] = mapped_column(ForeignKey("provider_profiles.id"), primary_key=True)
    insurance_plan_id: Mapped[int] = mapped_column(ForeignKey("insurance_plans.id"), primary_key=True)


class AvailabilitySlot(Base):
    __tablename__ = "availability_slots"
    __table_args__ = (
        CheckConstraint(f"status IN ({enum_values(SlotStatus)})", name="ck_slots_status"),
        CheckConstraint("end_at > start_at", name="ck_slots_end_after_start"),
        UniqueConstraint("provider_id", "start_at", "end_at", name="uq_provider_slot_time"),
        Index("ix_slots_provider_status_start", "provider_id", "status", "start_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("provider_profiles.id"), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SlotStatus.open.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    provider: Mapped[ProviderProfile] = relationship(back_populates="availability_slots")
    appointments: Mapped[list["AppointmentRequest"]] = relationship(back_populates="slot")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="slot")


class AppointmentRequest(Base):
    __tablename__ = "appointment_requests"
    __table_args__ = (
        CheckConstraint(f"status IN ({enum_values(AppointmentStatus)})", name="ck_appointments_status"),
        Index("ix_appointments_patient_status", "patient_id", "status"),
        Index("ix_appointments_provider_status", "provider_id", "status"),
        Index("ix_appointments_slot", "slot_id"),
        Index(
            "uq_active_appointment_per_slot",
            "slot_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'confirmed')"),
            sqlite_where=text("status IN ('pending', 'confirmed')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    provider_id: Mapped[int] = mapped_column(ForeignKey("provider_profiles.id"), nullable=False)
    slot_id: Mapped[int] = mapped_column(ForeignKey("availability_slots.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AppointmentStatus.pending.value
    )
    reason: Mapped[str | None] = mapped_column(Text)
    cancelled_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    patient: Mapped[User] = relationship(back_populates="appointments", foreign_keys=[patient_id])
    provider: Mapped[ProviderProfile] = relationship(back_populates="appointments")
    slot: Mapped[AvailabilitySlot] = relationship(back_populates="appointments")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="appointment_request")


class SlotWatcher(Base):
    __tablename__ = "slot_watchers"
    __table_args__ = (
        CheckConstraint("start_before > start_after", name="ck_watchers_valid_window"),
        Index("ix_watchers_patient", "patient_id"),
        Index("ix_watchers_provider_active", "provider_id", "is_active"),
        Index(
            "uq_active_watcher_window",
            "patient_id",
            "provider_id",
            "start_after",
            "start_before",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    provider_id: Mapped[int] = mapped_column(ForeignKey("provider_profiles.id"), nullable=False)
    start_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProviderFollow(Base):
    __tablename__ = "provider_follows"
    __table_args__ = (
        Index("ix_provider_follows_patient", "patient_id"),
        Index("ix_provider_follows_provider_active", "provider_id", "is_active"),
        Index(
            "uq_active_provider_follow",
            "patient_id",
            "provider_id",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    provider_id: Mapped[int] = mapped_column(ForeignKey("provider_profiles.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    patient: Mapped[User] = relationship(back_populates="provider_follows")
    provider: Mapped[ProviderProfile] = relationship(back_populates="followers")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            f"type IN ({enum_values(NotificationType)})", name="ck_notifications_type"
        ),
        Index(
            "uq_notification_dedupe",
            "user_id",
            "slot_id",
            "appointment_request_id",
            "type",
            unique=True,
            postgresql_where=text("appointment_request_id IS NOT NULL"),
            sqlite_where=text("appointment_request_id IS NOT NULL"),
        ),
        Index(
            "uq_notification_slot_event_dedupe",
            "user_id",
            "slot_id",
            "type",
            unique=True,
            postgresql_where=text("appointment_request_id IS NULL"),
            sqlite_where=text("appointment_request_id IS NULL"),
        ),
        Index("ix_notifications_user_read_created", "user_id", "is_read", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    slot_id: Mapped[int] = mapped_column(ForeignKey("availability_slots.id"), nullable=False)
    appointment_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointment_requests.id")
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="notifications")
    slot: Mapped[AvailabilitySlot] = relationship(back_populates="notifications")
    appointment_request: Mapped[AppointmentRequest | None] = relationship(back_populates="notifications")

    @property
    def provider_id(self) -> int:
        return self.slot.provider_id

    @property
    def provider_name(self) -> str:
        return self.slot.provider.display_name

    @property
    def start_at(self) -> datetime:
        if self.slot.start_at.tzinfo is None:
            return self.slot.start_at.replace(tzinfo=UTC)
        return self.slot.start_at

    @property
    def end_at(self) -> datetime:
        if self.slot.end_at.tzinfo is None:
            return self.slot.end_at.replace(tzinfo=UTC)
        return self.slot.end_at


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(f"status IN ({enum_values(OutboxStatus)})", name="ck_outbox_status"),
        Index("ix_outbox_status_created", "status", "created_at"),
        Index("ix_outbox_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=OutboxStatus.pending.value)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stream_message_id: Mapped[str | None] = mapped_column(String(80))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()
