# ProSiT - Process Simulation Tool

## Overview

ProSiT is a Flask-based web application for process mining and simulation. It allows users to upload XES (eXtensible Event Stream) event log files, discover process models using inductive mining techniques, and perform process simulations. The application provides a web interface for managing simulation sessions and visualizing process discovery results.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend Architecture
- **Framework**: Bootstrap 5 with custom CSS styling
- **JavaScript**: Vanilla JavaScript with Bootstrap components
- **UI Theme**: Purple and green color scheme
- **Icons**: Feather Icons library
- **Structure**: Template-based rendering using Jinja2

### Backend Architecture
- **Framework**: Flask (Python web framework)
- **Database ORM**: SQLAlchemy with Flask-SQLAlchemy extension
- **File Handling**: Werkzeug utilities for secure file uploads
- **Logging**: Python's built-in logging module with DEBUG level
- **Process Integration**: Custom ProSiT integration layer (mock implementation)

### Data Storage
- **Primary Database**: PostgreSQL database with automatic table creation
- **Database Schema**: SimulationSession table with fields for filename, noise_threshold, parameters (JSON), created_at, and status
- **File Storage**: Local filesystem for uploaded XES files and simulation results
- **Session Management**: Flask sessions with configurable secret key

## Key Components

### Models (`models.py`)
- **SimulationSession**: Core entity tracking uploaded files, parameters, and processing status
  - Stores filename, noise threshold, discovered parameters (JSON), timestamps, and status
  - Provides JSON serialization/deserialization for parameters

### Routes (`routes.py`)
- **File Upload Endpoint** (`/api/upload`): Handles XES file uploads with validation
- **Main Dashboard** (`/`): Displays recent sessions and upload interface
- **File Type Validation**: Restricts uploads to XES format only

### Process Integration (`prosit_integration.py`)
- **ProSiTIntegration Class**: Interface for process mining operations
- **Process Discovery**: Mock implementation of inductive miner algorithm
- **Parameter Extraction**: Transition weights and resource assignments
- **Future Integration Point**: Designed for PM4Py library integration

### Configuration
- **File Limits**: 100MB maximum upload size
- **Directory Structure**: Separate folders for uploads and simulations
- **Database Pooling**: Connection recycling and health checks enabled
- **Development Mode**: Debug logging and hot reload

## Data Flow

1. **File Upload**: User uploads XES file through web interface
2. **Session Creation**: New SimulationSession record created with 'uploaded' status
3. **Process Discovery**: ProSiTIntegration analyzes file to extract process model
4. **Parameter Storage**: Discovered parameters saved as JSON files using ProSiT's to_json method
5. **JSON Loading**: Parameters loaded back from JSON to ensure correct format conversion
6. **Status Updates**: Session status progresses through: uploaded → discovered → ready → simulating → completed
7. **Database Persistence**: Session metadata stored in PostgreSQL, parameters in JSON files for ProSiT compatibility

## Recent Changes (July 2025)

### ProSiT JSON Integration Update
- **Fixed critical data loading issues** with ProSiT library's new JSON format
- **Resource weights**: Now correctly extracted from JSON (previously all identical)
- **Activity assignments**: Properly loaded from act_to_resources data structure
- **Distribution parameters**: Authentic values from ProSiT JSON (fixed, norm, expon, lognorm)
- **Parameter conversion**: Complete rewrite to handle ProSiT's to_json/from_json methods
- **Data persistence**: JSON files for parameters, PostgreSQL for session metadata

### Parameter Persistence and Simulation Fixes (July 31, 2025)
- **Fixed parameter modification storage**: User changes to distribution parameters now persist correctly in ProSiT JSON format instead of reverting to defaults
- **Fixed simulation data source**: Simulations now use stored modified parameters from JSON files instead of rediscovering from original XES files
- **Enhanced resource addition**: New resources automatically added to all parameter sections (weights, calendars, waiting times) with proper alphabetical sorting
- **Parameter validation**: Improved conversion logic to preserve user modifications during format conversions
- **ProSiT JSON compatibility**: Fixed missing 'params' fields in uniform distributions and enhanced parameter conversion logic
- **Known limitation**: ProSiT library runtime error with DecisionRules during simulation execution (library compatibility issue)

## External Dependencies

### Python Packages
- **Flask**: Web framework and routing
- **SQLAlchemy**: Database ORM and migrations
- **Werkzeug**: File handling and security utilities
- **NumPy**: Numerical computations (for future ML features)

### Frontend Libraries
- **Bootstrap 5**: UI framework and components
- **Feather Icons**: Icon library for consistent UI
- **Vanilla JavaScript**: No heavy frontend framework dependencies

### File Format Support
- **XES Files**: Industry standard for event log data
- **JSON**: Parameter storage and API responses
- **XML**: Potential future support for process model export

## Deployment Strategy

### Development Setup
- **PostgreSQL Database**: Full-featured database for development and production
- **File System Storage**: Local directories for uploads
- **Debug Mode**: Detailed logging and auto-reload
- **Host Configuration**: Binds to all interfaces (0.0.0.0:5000)

### Production Considerations
- **Database**: PostgreSQL database with connection pooling and health checks
- **Proxy Support**: ProxyFix middleware for reverse proxy deployment
- **Security**: Configurable session secrets via environment variables
- **File Management**: Organized directory structure with timestamp prefixes

### Scalability Features
- **Database Connection Pooling**: Prevents connection exhaustion
- **Stateless Session Management**: Supports horizontal scaling
- **Modular Architecture**: Easy to extend with additional process mining algorithms

The application is designed as a foundation for process mining workflows, with clear separation between data persistence, business logic, and presentation layers. The mock ProSiT integration provides a structure for future integration with sophisticated process mining libraries like PM4Py.