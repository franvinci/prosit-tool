# Use Python 3.10 slim image as base
FROM python:3.10-slim

# Set build arguments for architecture detection
ARG TARGETARCH
ARG TARGETPLATFORM

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

# The conda environment installs the tool itself (pip install -e .), so the
# sources have to be in place before the environment is created.
COPY . .

# Install conda and create environment
RUN apt-get update && apt-get install -y wget && \
    if [ "$TARGETARCH" = "amd64" ] || [ "$TARGETARCH" = "x86_64" ]; then \
        MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"; \
    elif [ "$TARGETARCH" = "arm64" ] || [ "$TARGETARCH" = "aarch64" ]; then \
        MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh"; \
    else \
        echo "Unsupported architecture: $TARGETARCH" && exit 1; \
    fi && \
    echo "Downloading Miniconda for architecture: $TARGETARCH" && \
    wget "$MINICONDA_URL" -O miniconda.sh && \
    bash miniconda.sh -b -p /opt/conda && \
    rm miniconda.sh && \
    /opt/conda/bin/conda config --set always_yes true && \
    /opt/conda/bin/conda config --set auto_activate_base false && \
    /opt/conda/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    /opt/conda/bin/conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r && \
    /opt/conda/bin/conda env create -f environment.yml && \
    /opt/conda/bin/conda clean -afy && \
    rm -rf /var/lib/apt/lists/*

# Use the Python of the environment created above (named in environment.yml)
ENV PATH="/opt/conda/envs/prosit-tool/bin:$PATH"

# Create necessary directories
RUN mkdir -p uploads simulations instance

# Set environment variables
ENV PYTHONPATH=/app
# Inside a container the server must accept connections from outside it, and
# there is no browser to open.
ENV PROSIT_TOOL_HOST=0.0.0.0
ENV PROSIT_TOOL_NO_BROWSER=1

# Expose port
EXPOSE 5050

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5050/ || exit 1

# Run the application
CMD ["python", "main.py"]
