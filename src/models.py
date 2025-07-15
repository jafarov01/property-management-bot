# FILE: models.py
# ==============================================================================
# VERSION: 3.0 (Production)
# UPDATED: Increased the size of the 'property_code' column in the EmailAlert
# table to String(255) to prevent 'DataError' for long property names.
# ==============================================================================
from sqlalchemy import Column, Integer, String, Date, ForeignKey, Text, DateTime, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Property(Base):
    __tablename__ = "properties"
    id = Column(Integer, primary_key=True)
    code = Column(String(10), unique=True, index=True, nullable=False)
    status = Column(String(50), default="AVAILABLE", nullable=False, index=True)
    notes = Column(Text, nullable=True)
    bookings = relationship("Booking", back_populates="property", cascade="all, delete-orphan")
    issues = relationship("Issue", back_populates="property", cascade="all, delete-orphan")

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    property_code = Column(String(10), index=True, nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True)
    guest_name = Column(String(255), nullable=False)
    platform = Column(String(20))
    checkin_date = Column(Date, nullable=False, index=True)
    checkout_date = Column(Date, index=True, nullable=True)
    due_payment = Column(String(100))
    status = Column(String(50), default="Active", index=True)
    property = relationship("Property", back_populates="bookings")

class Issue(Base):
    __tablename__ = "issues"
    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    reported_at = Column(Date, server_default=func.now(), nullable=False)
    description = Column(Text, nullable=False)
    is_resolved = Column(String(10), default="No", nullable=False)
    property = relationship("Property", back_populates="issues")

class Relocation(Base):
    __tablename__ = "relocations"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    guest_name = Column(String(255), nullable=False)
    original_property_code = Column(String(10), nullable=False)
    new_property_code = Column(String(10), nullable=False)
    relocated_at = Column(DateTime(timezone=True), server_default=func.now())
    booking = relationship("Booking")

class EmailAlert(Base):
    __tablename__ = "email_alerts"
    id = Column(Integer, primary_key=True, index=True)
    telegram_message_id = Column(BigInteger, nullable=True, index=True)
    category = Column(String(100), nullable=False)
    status = Column(String(20), default="OPEN", nullable=False, index=True)
    handled_by = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    handled_at = Column(DateTime(timezone=True), nullable=True)
    
    # --- Columns to store parsed data ---
    summary = Column(Text, nullable=True)
    guest_name = Column(String(255), nullable=True)
    # THE FIX: Increased size to handle long property names from emails.
    property_code = Column(String(255), nullable=True) 
    platform = Column(String(50), nullable=True)
    reservation_number = Column(String(50), nullable=True)
    deadline = Column(String(100), nullable=True)
