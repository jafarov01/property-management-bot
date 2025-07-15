# FILE: models.py
# ==============================================================================
# VERSION: 4.0 (Production)
# UPDATED: Aggressively increased the size of all variable-length string
# columns across all tables to prevent any future 'DataError' issues.
# ==============================================================================
from sqlalchemy import Column, Integer, String, Date, ForeignKey, Text, DateTime, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Property(Base):
    __tablename__ = "properties"
    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, index=True, nullable=False) # Increased
    status = Column(String(50), default="AVAILABLE", nullable=False, index=True)
    notes = Column(Text, nullable=True)
    bookings = relationship("Booking", back_populates="property", cascade="all, delete-orphan")
    issues = relationship("Issue", back_populates="property", cascade="all, delete-orphan")

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    property_code = Column(String(50), index=True, nullable=False) # Increased
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True)
    guest_name = Column(String(1024), nullable=False) # Increased
    platform = Column(String(255)) # Increased
    checkin_date = Column(Date, nullable=False, index=True)
    checkout_date = Column(Date, index=True, nullable=True)
    due_payment = Column(String(255)) # Increased
    status = Column(String(50), default="Active", index=True)
    property = relationship("Property", back_populates="bookings")

class Issue(Base):
    __tablename__ = "issues"
    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    reported_at = Column(Date, server_default=func.now(), nullable=False)
    description = Column(Text, nullable=False)
    is_resolved = Column(String(50), default="No", nullable=False) # Increased
    property = relationship("Property", back_populates="issues")

class Relocation(Base):
    __tablename__ = "relocations"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    guest_name = Column(String(1024), nullable=False) # Increased
    original_property_code = Column(String(50), nullable=False) # Increased
    new_property_code = Column(String(50), nullable=False) # Increased
    relocated_at = Column(DateTime(timezone=True), server_default=func.now())
    booking = relationship("Booking")

class EmailAlert(Base):
    __tablename__ = "email_alerts"
    id = Column(Integer, primary_key=True, index=True)
    telegram_message_id = Column(BigInteger, nullable=True, index=True)
    category = Column(String(255), nullable=False) # Increased
    status = Column(String(50), default="OPEN", nullable=False, index=True) # Increased
    handled_by = Column(String(1024), nullable=True) # Increased
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    handled_at = Column(DateTime(timezone=True), nullable=True)
    
    # --- Columns to store parsed data ---
    summary = Column(Text, nullable=True)
    guest_name = Column(String(1024), nullable=True) # Increased
    property_code = Column(String(1024), nullable=True) # Increased
    platform = Column(String(255), nullable=True) # Increased
    reservation_number = Column(String(255), nullable=True) # Increased
    deadline = Column(String(255), nullable=True) # Increased
