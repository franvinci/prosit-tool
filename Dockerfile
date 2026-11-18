# ProSiT Tool in a container: the web application, on port 5050.
#
#   docker build -t prosit-tool .
#   docker run --rm -p 127.0.0.1:5050:5050 -v prosit-data:/data prosit-tool
#
# Everything comes from PyPI as ready-made wheels: there is nothing to compile
# and no Graphviz to install (the diagrams are drawn by the browser).

ARG PYTHON_VERSION=3.12

# --- the tool and what it needs, in a virtual environment ---------------------
FROM python:${PYTHON_VERSION}-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN python -m venv /opt/prosit
ENV PATH="/opt/prosit/bin:$PATH"
WORKDIR /src

# The dependencies first, at the versions the release was tested with: this
# layer is built again only when they change.
COPY pyproject.toml ./
COPY packaging/constraints.txt packaging/
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > requirements.txt \
    && pip install -c packaging/constraints.txt -r requirements.txt

# Then the tool itself.
COPY README.md LICENSE THIRD-PARTY-LICENSES ./
COPY prosit_tool prosit_tool
RUN pip install --no-deps .

# What the image contains, with the licence of each part and where its source is.
COPY packaging/third_party_notices.py packaging/
RUN mkdir -p /opt/prosit/share/doc/prosit-tool \
    && cp LICENSE /opt/prosit/share/doc/prosit-tool/ \
    && python packaging/third_party_notices.py --output /opt/prosit/share/doc/prosit-tool/THIRD-PARTY-NOTICES.txt

# --- the image -----------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim

LABEL org.opencontainers.image.title="ProSiT Tool" \
      org.opencontainers.image.description="Web tool for data-driven business process simulation, built on prosit-pm" \
      org.opencontainers.image.source="https://github.com/franvinci/prosit-tool" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

COPY --from=build /opt/prosit /opt/prosit

# Uploaded logs, simulations and the database are kept under /data: mount a
# volume there to keep them. Inside a container the server has to accept
# connections from outside it, and there is no browser to open.
ENV PATH="/opt/prosit/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    PROSIT_TOOL_DATA_DIR=/data \
    PROSIT_TOOL_HOST=0.0.0.0 \
    PROSIT_TOOL_NO_BROWSER=1

EXPOSE 5050

HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5050/api/health', timeout=4)" || exit 1

CMD ["prosit-tool"]
