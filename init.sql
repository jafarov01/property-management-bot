-- Initialize the Eivissa Operations Database
-- This script creates the database and sets up initial permissions

-- Create the database (this is handled by POSTGRES_DB environment variable)
-- CREATE DATABASE eivissa_operations;

-- Grant permissions to the user
GRANT ALL PRIVILEGES ON DATABASE eivissa_operations TO eivissa_user;

-- Create extensions if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Set timezone
SET timezone = 'Europe/Budapest';