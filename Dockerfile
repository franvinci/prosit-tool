# Use Python 3.10 slim image as base
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    graphviz \
    libgraphviz-dev \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy environment file first for better caching
COPY environment.yml .

# Install conda and create environment
RUN apt-get update && apt-get install -y wget && \
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh && \
    bash miniconda.sh -b -p /opt/conda && \
    rm miniconda.sh && \
    /opt/conda/bin/conda config --set always_yes true && \
    /opt/conda/bin/conda config --set auto_activate_base false && \
    /opt/conda/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    /opt/conda/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r && \
    /opt/conda/bin/conda env create -f environment.yml && \
    /opt/conda/bin/conda clean -afy && \
    rm -rf /var/lib/apt/lists/*

# Add conda to PATH
ENV PATH="/opt/conda/envs/prosit/bin:$PATH"

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p uploads simulations instance

# Set environment variables
ENV FLASK_APP=main.py
ENV FLASK_ENV=production
ENV PYTHONPATH=/app

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Run the application
CMD ["python", "main.py"]
