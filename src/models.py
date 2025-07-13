# FILE: models.py
# ==============================================================================
from sqlalchemy import Column, Integer, String, Date, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True)
    code = Column(String(10), unique=True, index=True, nullable=False)
    status = Column(String(50), default="AVAILABLE", nullable=False, index=True)
    notes = Column(Text, nullable=True) # For storing block/maintenance reasons

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