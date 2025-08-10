# FILE: app/models.py
# VERSION: 6.0 (Refactored for Enums & Reminders)
# ==============================================================================
# UPDATED: This version introduces significant robustness improvements.
# 1. All `status` columns now use strict Enum types to prevent invalid data.
# 2. Added `reminders_sent` to Bookings for the new unified reminder system.
# 3. Added `email_uid` to EmailAlerts to support the immediate-notify workflow.
# ==============================================================================
import enum
from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    ForeignKey,
    Text,
    DateTime,
    BigInteger,
    Enum as SAEnum,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

# --- ENUM DEFINITIONS FOR STATUSES ---

class PropertyStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    PENDING_CLEANING = "PENDING_CLEANING"
    MAINTENANCE = "MAINTENANCE"

class BookingStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"
    PENDING_RELOCATION = "PENDING_RELOCATION"

class EmailAlertStatus(str, enum.Enum):
    OPEN = "OPEN"
    HANDLED = "HANDLED"
    PARSING_FAILED = "PARSING_FAILED"

# --- TABLE MODELS ---

class Property(Base):
    __tablename__ = "properties"
    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    status = Column(
        SAEnum(PropertyStatus, native_enum=False),
        default=PropertyStatus.AVAILABLE,
        nullable=False,
        index=True,
    )
    notes = Column(Text, nullable=True)
    bookings = relationship(
        "Booking", back_populates="property", cascade="all, delete-orphan"
    )
    issues = relationship(
        "Issue", back_populates="property", cascade="all, delete-orphan"
    )


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    property_code = Column(String(50), index=True, nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True)
    guest_name = Column(String(1024), nullable=False)
    platform = Column(String(255))
    checkin_date = Column(Date, nullable=False, index=True)
    checkout_date = Column(Date, index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now()) # Added for reminder logic
    due_payment = Column(String(255))
    status = Column(
        SAEnum(BookingStatus, native_enum=False),
        default=BookingStatus.ACTIVE,
        index=True,
    )
    reminders_sent = Column(Integer, default=0, nullable=False) # New column for reminders
    property = relationship("Property", back_populates="bookings")


class Issue(Base):
    __tablename__ = "issues"
    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    reported_at = Column(Date, server_default=func.now(), nullable=False)
    description = Column(Text, nullable=False)
    is_resolved = Column(String(50), default="No", nullable=False)
    property = relationship("Property", back_populates="issues")


class Relocation(Base):
    __tablename__ = "relocations"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    guest_name = Column(String(1024), nullable=False)
    original_property_code = Column(String(50), nullable=False)
    new_property_code = Column(String(50), nullable=False)
    relocated_at = Column(DateTime(timezone=True), server_default=func.now())
    booking = relationship("Booking")


class EmailAlert(Base):
    __tablename__ = "email_alerts"
    id = Column(Integer, primary_key=True, index=True)
    telegram_message_id = Column(BigInteger, nullable=True, index=True)
    email_uid = Column(String(255), nullable=True, index=True) # New column for IMAP UID
    category = Column(String(255), nullable=False)
    status = Column(
        SAEnum(EmailAlertStatus, native_enum=False),
        default=EmailAlertStatus.OPEN,
        nullable=False,
        index=True,
    )
    handled_by = Column(String(1024), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    handled_at = Column(DateTime(timezone=True), nullable=True)
    reminders_sent = Column(Integer, default=0, nullable=False)

    # --- Columns to store parsed data ---
    summary = Column(Text, nullable=True)
    guest_name = Column(String(1024), nullable=True)
    property_code = Column(String(1024), nullable=True)
    platform = Column(String(255), nullable=True)
    reservation_number = Column(String(255), nullable=True)
    deadline = Column(String(255), nullable=True)