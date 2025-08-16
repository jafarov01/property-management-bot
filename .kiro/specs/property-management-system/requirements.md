# Requirements Document

## Introduction

The Eivissa Operations Bot is an intelligent, multi-platform property management system designed to digitize and automate daily operations for a property management business. The system acts as a centralized command center that processes check-in lists from Slack, parses critical emails from Gmail, manages overbooking conflicts, and provides real-time operational control via Telegram. The system integrates AI-powered parsing capabilities using Google's Gemini AI to transform unstructured data into actionable operational insights.

## Requirements

### Requirement 1: Multi-Platform Data Ingestion

**User Story:** As a property manager, I want the system to automatically ingest operational data from multiple platforms (Slack, Gmail, Telegram), so that I can manage all property operations from a single centralized system.

#### Acceptance Criteria

1. WHEN a check-in list is posted in the designated Slack channel THEN the system SHALL parse the message and create booking records in the database
2. WHEN a cleaning list is posted in the designated Slack channel THEN the system SHALL update property statuses to reflect cleaning requirements
3. WHEN new unread emails arrive in the monitored Gmail inbox THEN the system SHALL fetch and parse them for operational alerts
4. WHEN email subjects contain ignored keywords (security alert, promotional, weekly report, your invoice) THEN the system SHALL mark them as read without processing
5. WHEN Telegram commands are received THEN the system SHALL process them and provide appropriate responses
6. IF unauthorized users attempt to post lists in Slack THEN the system SHALL ignore their messages
7. WHEN the system receives a "great reset" command THEN the system SHALL wipe all data and reseed the database with available properties

### Requirement 2: AI-Powered Content Parsing

**User Story:** As a property manager, I want the system to automatically parse unstructured messages and emails using AI, so that I don't have to manually extract and enter operational data.

#### Acceptance Criteria

1. WHEN a Slack check-in list is received THEN the system SHALL use Gemini AI to extract property codes, guest names, platforms, and payment information
2. WHEN a Slack cleaning list is received THEN the system SHALL use Gemini AI to extract property codes that need cleaning
3. WHEN an email is received THEN the system SHALL use Gemini AI to extract category, summary, guest name, property code, platform, reservation number, and deadline
4. WHEN AI parsing fails THEN the system SHALL create an alert with status "PARSING_FAILED"
5. WHEN extracted property codes don't exist in the database THEN the system SHALL suggest similar codes using fuzzy matching
6. IF AI response doesn't contain valid JSON THEN the system SHALL return a parsing failed status with appropriate error message

### Requirement 3: Property Status Management

**User Story:** As a property manager, I want the system to track and manage property statuses in real-time, so that I can maintain accurate operational visibility.

#### Acceptance Criteria

1. WHEN a property is checked in THEN the system SHALL change its status from AVAILABLE to OCCUPIED
2. WHEN a property is checked out THEN the system SHALL change its status from OCCUPIED to PENDING_CLEANING
3. WHEN a property is cleaned THEN the system SHALL change its status from PENDING_CLEANING to AVAILABLE
4. WHEN a property needs maintenance THEN the system SHALL change its status to MAINTENANCE with reason notes
5. WHEN maintenance is complete THEN the system SHALL change its status from MAINTENANCE to AVAILABLE
6. WHEN a property status is updated THEN the system SHALL enforce enum constraints (AVAILABLE, OCCUPIED, PENDING_CLEANING, MAINTENANCE)
7. IF an invalid status is attempted THEN the system SHALL reject the change and maintain data integrity

### Requirement 4: Booking Lifecycle Management

**User Story:** As a property manager, I want the system to manage the complete booking lifecycle from check-in to departure, so that I can track guest stays and property utilization.

#### Acceptance Criteria

1. WHEN a new booking is created THEN the system SHALL store property code, guest name, platform, check-in date, due payment, and status
2. WHEN a guest checks out THEN the system SHALL update the booking status to DEPARTED and set checkout date
3. WHEN a booking is cancelled THEN the system SHALL update the booking status to CANCELLED and make the property available
4. WHEN booking details need updates THEN the system SHALL allow editing of guest name, due payment, and platform
5. WHEN a booking is created THEN the system SHALL enforce enum constraints (ACTIVE, DEPARTED, CANCELLED, PENDING_RELOCATION)
6. WHEN checkout reminders are needed THEN the system SHALL schedule them for the day before checkout at 18:00
7. IF a booking conflicts with an existing booking THEN the system SHALL create a PENDING_RELOCATION status

### Requirement 5: Overbooking Conflict Resolution

**User Story:** As a property manager, I want the system to automatically detect and provide resolution options for overbooking conflicts, so that I can quickly resolve guest accommodation issues.

#### Acceptance Criteria

1. WHEN a check-in is attempted for an occupied property THEN the system SHALL create a conflict alert with interactive buttons
2. WHEN a conflict alert is created THEN the system SHALL provide "Swap", "Cancel", and "Show Available" options
3. WHEN "Show Available" is clicked THEN the system SHALL display all properties with AVAILABLE status
4. WHEN "Swap" is clicked THEN the system SHALL exchange the active and pending booking statuses
5. WHEN "Cancel" is clicked THEN the system SHALL cancel the pending booking and resolve the conflict
6. WHEN a swap is performed THEN the system SHALL update the conflict alert with new booking information
7. WHEN a conflict is resolved THEN the system SHALL remove all interactive buttons from the alert

### Requirement 6: Email Alert Management

**User Story:** As a property manager, I want the system to monitor and alert me about important emails, so that I can respond to guest issues and operational matters promptly.

#### Acceptance Criteria

1. WHEN new unread emails are detected THEN the system SHALL create email alerts with parsed information
2. WHEN an email alert is created THEN the system SHALL include category, summary, guest name, property code, platform, reservation number, and deadline
3. WHEN an email alert is sent to Telegram THEN the system SHALL include a "Handle" button for staff interaction
4. WHEN the "Handle" button is clicked THEN the system SHALL mark the alert as HANDLED with handler name and timestamp
5. WHEN email alerts remain unhandled THEN the system SHALL send reminder notifications every 5 minutes
6. WHEN an email is processed THEN the system SHALL mark it as read in the Gmail inbox
7. IF email parsing fails THEN the system SHALL create an alert with PARSING_FAILED status

### Requirement 7: Telegram Command Interface

**User Story:** As a property manager, I want comprehensive Telegram commands to query and control all system operations, so that I can manage properties remotely and efficiently.

#### Acceptance Criteria

1. WHEN /status is executed THEN the system SHALL return a summary of all property statuses with counts
2. WHEN /check [property_code] is executed THEN the system SHALL return detailed property information including active booking and issues
3. WHEN /available is executed THEN the system SHALL list all properties with AVAILABLE status
4. WHEN /occupied is executed THEN the system SHALL list all properties with OCCUPIED status
5. WHEN /pending_cleaning is executed THEN the system SHALL list all properties with PENDING_CLEANING status
6. WHEN /early_checkout [property_code] is executed THEN the system SHALL change occupied property to PENDING_CLEANING
7. WHEN /set_clean [property_code] is executed THEN the system SHALL change pending cleaning property to AVAILABLE
8. WHEN /cancel_booking [property_code] is executed THEN the system SHALL cancel active booking and make property available
9. WHEN /relocate [from_code] [to_code] [date] is executed THEN the system SHALL move pending relocation guest to available property
10. WHEN /block_property [property_code] [reason] is executed THEN the system SHALL set property to MAINTENANCE with reason
11. WHEN /unblock_property [property_code] is executed THEN the system SHALL change maintenance property to AVAILABLE
12. WHEN /edit_booking [property_code] [field] [value] is executed THEN the system SHALL update the specified booking field
13. WHEN /log_issue [property_code] [description] is executed THEN the system SHALL create a new maintenance issue
14. WHEN /booking_history [property_code] is executed THEN the system SHALL show last 5 bookings for the property
15. WHEN /find_guest [name] is executed THEN the system SHALL locate active bookings matching the guest name
16. WHEN /daily_revenue [date] is executed THEN the system SHALL calculate estimated revenue for the specified date
17. WHEN /relocations is executed THEN the system SHALL show recent guest relocation history
18. WHEN /rename_property [old_code] [new_code] is executed THEN the system SHALL update property code and all related bookings
19. WHEN /help is executed THEN the system SHALL display the complete command manual

### Requirement 8: Automated Task Scheduling

**User Story:** As a property manager, I want the system to automatically perform routine tasks and send reminders, so that I don't miss important operational deadlines.

#### Acceptance Criteria

1. WHEN the system starts THEN the system SHALL schedule daily midnight cleaning task at 00:05
2. WHEN the system starts THEN the system SHALL schedule daily briefing task at 10:00
3. WHEN the system starts THEN the system SHALL schedule email checking task every 1 minute
4. WHEN the system starts THEN the system SHALL schedule unhandled issue reminder task every 5 minutes
5. WHEN a late cleaning list is detected THEN the system SHALL schedule a dynamic midnight task 15 minutes later
6. WHEN a booking is relocated THEN the system SHALL schedule a checkout reminder for the day before checkout at 18:00
7. WHEN midnight task runs THEN the system SHALL change all PENDING_CLEANING properties to AVAILABLE
8. WHEN briefing task runs THEN the system SHALL send operational summary to Telegram
9. WHEN email checking task runs THEN the system SHALL fetch new emails and queue them for processing
10. WHEN reminder task runs THEN the system SHALL send notifications for unhandled email alerts

### Requirement 9: Data Integrity and Validation

**User Story:** As a property manager, I want the system to maintain data integrity and validate all inputs, so that the operational data remains accurate and reliable.

#### Acceptance Criteria

1. WHEN property status is updated THEN the system SHALL enforce enum constraints (AVAILABLE, OCCUPIED, PENDING_CLEANING, MAINTENANCE)
2. WHEN booking status is updated THEN the system SHALL enforce enum constraints (ACTIVE, DEPARTED, CANCELLED, PENDING_RELOCATION)
3. WHEN email alert status is updated THEN the system SHALL enforce enum constraints (OPEN, HANDLED, PARSING_FAILED)
4. WHEN property codes are entered THEN the system SHALL validate they exist in the database
5. WHEN dates are entered THEN the system SHALL validate they are in correct ISO format (YYYY-MM-DD)
6. WHEN booking fields are edited THEN the system SHALL validate only allowed fields (guest_name, due_payment, platform)
7. WHEN database operations fail THEN the system SHALL rollback transactions to maintain consistency
8. WHEN invalid commands are received THEN the system SHALL provide usage instructions
9. WHEN property codes don't exist THEN the system SHALL suggest similar codes using fuzzy matching
10. IF concurrent access occurs THEN the system SHALL use row locking to prevent race conditions

### Requirement 10: System Monitoring and Error Handling

**User Story:** As a property manager, I want the system to handle errors gracefully and provide monitoring capabilities, so that I can maintain system reliability and troubleshoot issues.

#### Acceptance Criteria

1. WHEN critical errors occur THEN the system SHALL log them with full stack traces
2. WHEN Slack processing fails THEN the system SHALL send error alerts to Telegram issues topic
3. WHEN email parsing fails THEN the system SHALL create alerts with PARSING_FAILED status
4. WHEN database operations fail THEN the system SHALL rollback transactions and log errors
5. WHEN Telegram commands fail THEN the system SHALL provide user-friendly error messages
6. WHEN the system starts THEN the system SHALL initialize database tables if they don't exist
7. WHEN webhooks are set THEN the system SHALL configure Telegram webhook URL automatically
8. WHEN the system shuts down THEN the system SHALL gracefully stop all scheduled tasks and close connections
9. WHEN debug information is needed THEN the system SHALL provide table description endpoint
10. IF memory or performance issues occur THEN the system SHALL use async operations and connection pooling