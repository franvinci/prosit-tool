# 🚀 ProSiT - Process Simulation Tool

ProSiT (Process Simulation Tool) is a comprehensive, user-friendly environment for data-driven business process simulation that addresses the limitations of existing solutions in accessibility, configurability, and interpretability. Unlike traditional black-box deep learning approaches, ProSiT integrates state-of-the-art machine learning methods in an explainable, white-box form, empowering service architects and process analysts to experiment with alternative designs and evaluate service-level impacts.

ProSiT provides a controlled environment for "what-if" analyses and process optimization by supporting (i) ingestion of event logs and process models, (ii) automated discovery of control-flow, timing, resource, and trace attribute parameters, (iii) interactive configuration of alternative service scenarios, (iv) visualization of accuracy metrics, and (v) generation and statistical analysis of simulated event logs. By combining simulation accuracy with transparency, ProSiT enables organizations to explore optimization opportunities through an intuitive graphical interface.


## ✨ Features

- **Event Log Processing**: Upload and process XES event logs with support for various attributes
- **Process Discovery**: Automatic discovery of Petri nets from event logs using PM4Py
- **Parameter Discovery**: Intelligent discovery of simulation parameters including:
  - Control flow probabilities
  - Resource assignments and calendars
  - Arrival, execution and waiting time distributions
  - Trace attributes distribution
- **Process Simulation**: Run discrete-event simulations with realistic parameters
- **Visualization**: Generate process models, performance metrics, and simulation results
- **Web Interface**: User-friendly web interface for all operations
- **Docker Support**: Easy deployment using Docker containers

## 💻 System Requirements

### Minimum Requirements
- **RAM**: 4GB (8GB recommended)
- **Storage**: 2GB free space
- **OS**: Windows 10/11, Ubuntu 18.04+, or macOS 10.14+

### For Docker Installation
- Docker Desktop (Windows/macOS) or Docker Engine (Linux)
- Docker Compose

## 🚀 Quick Start

### Option 1: Docker Installation (Recommended)

#### Windows
1. Download and install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
2. Run the setup script:
   ```cmd
   installer\windows\setup-windows.bat
   ```
3. Start the application:
   ```cmd
   installer\windows\run-docker.bat
   ```
4. Open your browser and go to `http://localhost:5000`

#### Ubuntu/Linux
1. Run the setup script:
   ```bash
   chmod +x installer/ubuntu/setup-ubuntu.sh
   ./installer/ubuntu/setup-ubuntu.sh
   ```
2. Log out and log back in (or restart)
3. Start the application:
   ```bash
   ./installer/ubuntu/run-docker.sh
   ```
4. Open your browser and go to `http://localhost:5000`

#### macOS
1. Run the setup script:
   ```bash
   chmod +x installer/macos/setup-macos.sh
   ./installer/macos/setup-macos.sh
   ```
2. Follow the instructions to install Docker Desktop
3. Start Docker Desktop from Applications folder or Spotlight
4. Start the application:
   ```bash
   ./installer/macos/run-docker.sh
   ```
5. Open your browser and go to `http://localhost:5000`

#### Manual Docker Setup
1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd prosit
   ```

2. Build and run with Docker Compose:
   ```bash
   docker-compose up -d --build
   ```

3. Access the application at `http://localhost:5000`

### Option 2: Local Installation

#### Prerequisites
- Python 3.10+
- Conda or Miniconda

#### Setup Steps
1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd prosit
   ```

2. Create the conda environment:
   ```bash
   conda env create -f environment.yml
   conda activate prosit
   ```

3. Install the application:
   ```bash
   pip install -e .
   ```

4. Run the application:
   ```bash
   python main.py
   ```

5. Access the application at `http://localhost:5000`

## 📖 Usage

ProSiT supports an end-to-end workflow for data-driven process simulation, guiding users through five key phases:

### 1. 📂 Data Ingestion
- **Event Log Upload**: Upload event logs in XES format through the intuitive web interface
- **Process Model Import**: Optionally provide your own process models in PNML format
- **Data Validation**: Ensure your XES file contains the required attributes:
  - `case:concept:name` (case identifier)
  - `concept:name` (activity name)
  - `start:timestamp` (activity start time)
  - `time:timestamp` (activity end time)
  - `org:resource` (resource identifier)

### 2. 🔍 Parameter Discovery
This core functionality uses explainable machine learning models to automatically extract simulation parameters from event logs:
- **Algorithm Configuration**: Tailor the discovery process by configuring:
  - Inductive Miner algorithm with specific noise threshold
  - Probabilistic decision trees with controllable depth
  - Incremental discovery with customizable grace periods
- **Comprehensive Discovery Coverage**:
  - **Control Flow**: Transition weights for decision points
  - **Resources**: Assignment probabilities, multitasking capabilities, and availability calendars
  - **Timing**: Arrival, execution, and waiting time distributions per activity
  - **Trace Attributes**: Distribution patterns for process variables

### 3. 🎯 Interactive Scenario Configuration
- **Intuitive Interface**: Modify discovered parameters through an intuitive graphical interface
- **Alternative Scenarios**: Create and compare multiple simulation scenarios
- **What-If Analysis**: Facilitate comprehensive scenario comparison for decision-making

### 4. 📊 Accuracy Assessment
The tool evaluates simulation quality by comparing generated logs with original event data:
- **Control-Flow Similarity**: N-gram distance measures for process structure accuracy
- **Temporal Accuracy**: Distributional metrics for timing realism
- **Resource Behavior**: Realism of resource handover patterns
- **Generalization Capability**: Entropy analysis for model robustness

### 5. 🚀 Simulation Execution
- **Configuration**: Define desired number of traces and starting timestamp
- **Execution**: Launch the simulation with real-time progress monitoring
- **Visual Analytics**: Access comprehensive results including:
  - Process maps annotated with performance data
  - Cycle time distributions and bottleneck analysis
  - Resource utilization heatmaps
  - Detailed activity execution and waiting time analyses
- **Export**: Download simulated event logs and analytics in multiple formats

## 🏗️ Project Structure

```
prosit/
├── 📱 app.py                 # Flask application configuration
├── 🚀 main.py               # Application entry point
├── 🗃️ models.py             # Database models and schemas
├── 🛣️ routes.py             # Web routes and API endpoints
├── 🔧 prosit_integration.py  # Core ProSiT integration layer
├── 📚 prosit/               # Core ProSiT library
├── 🎨 templates/           # HTML templates and UI components
├── 🎭 static/              # CSS, JavaScript, and static assets
├── 🔧 installer/           # Platform-specific setup scripts
│   ├── ubuntu/             # Linux installation scripts
│   ├── windows/            # Windows installation scripts
│   └── macos/              # macOS installation scripts
├── 📋 example_data/        # Sample XES files for testing
├── 🐳 docker-compose.yml   # Docker Compose configuration
├── 🐳 Dockerfile          # Docker image definition
├── 📦 environment.yml     # Conda environment specification
├── 📄 LICENSE             # MIT License
└── 📖 README.md           # This documentation
```

## 🏛️ System Architecture Diagram

![System Architecture](doc/diagram.png)

## 🔌 API Endpoints

- `GET /` - Main application interface
- `POST /upload` - Upload XES event log
- `POST /discover` - Discover process model
- `POST /simulate` - Run simulation
- `GET /results/<session_id>` - Get simulation results
- `GET /download/<session_id>/<file_type>` - Download result files

## ⚙️ Configuration

### Environment Variables
- `FLASK_ENV`: Set to `production` for production deployment
- `DATABASE_URL`: Database connection string (default: SQLite)
- `SESSION_SECRET`: Secret key for session management
- `MAX_CONTENT_LENGTH`: Maximum file upload size (default: 100MB)

### Database
The application uses SQLite by default, but can be configured to use other databases by setting the `DATABASE_URL` environment variable.

## 🔧 Troubleshooting

### Common Issues

1. **Docker not starting**
   - Ensure Docker Desktop is running
   - Check system requirements
   - Verify virtualization is enabled in BIOS (Windows/Linux)
   - For macOS: Ensure Docker Desktop is fully started (whale icon in menu bar)

2. **Port 5000 already in use**
   - Stop other services using port 5000
   - Modify `docker-compose.yml` to use a different port

3. **Memory issues during simulation**
   - Increase Docker memory allocation
   - Reduce simulation parameters (fewer cases, shorter duration)

4. **Architecture compatibility issues (macOS)**
   - The Dockerfile now automatically detects your Mac's architecture (Intel/Apple Silicon)
   - If you encounter build errors, ensure Docker Desktop is up to date
   - For Apple Silicon Macs, the build will use ARM64 architecture

5. **File upload errors**
   - Check file size (max 100MB)
   - Ensure XES file format is correct
   - Verify required attributes are present

### Logs and Debugging

- View application logs: `docker-compose logs -f`
- Check container status: `docker-compose ps`
- Restart application: `docker-compose restart`

## 👨‍💻 Development

### Setting up Development Environment
1. Clone the repository
2. Create conda environment: `conda env create -f environment.yml`
3. Activate environment: `conda activate prosit`
4. Install in development mode: `pip install -e .`
5. Run with debug mode: `FLASK_ENV=development python main.py`

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For issues and questions:
1. Check the troubleshooting section above
2. Review the application logs
3. Create an issue in the repository
4. Contact the development team
