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
    appointments: Mapped[list["AppointmentRequest"]] = relationship(
        back_populates="patient", foreign_keys="AppointmentRequest.patient_id"
    )
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user")
    provider_follows: Mapped[list["ProviderFollow"]] = relationship(back_populates="patient")


class ProviderProfile(Base):
    __tablename__ = "provider_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_provider_profiles_user_id"),
        Index("ix_provider_profiles_city_state", "city", "state"),
        Index("ix_provider_profiles_offers_virtual", "offers_virtual"),
        Index("ix_provider_profiles_offers_in_person", "offers_in_person"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    bio: Mapped[str] = mapped_column(Text, nullable=False, default="")
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="America/New_York")
    offers_virtual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    offers_in_person: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="provider_profile")
    specialties: Mapped[list["Specialty"]] = relationship(
        secondary="provider_specialties", back_populates="providers"
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

    provider_id: Mapped[int] = mapped_column(ForeignKey("provider_profiles.id"), primary_key=True)
    specialty_id: Mapped[int] = mapped_column(ForeignKey("specialties.id"), primary_key=True)


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
