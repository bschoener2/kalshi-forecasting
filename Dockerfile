FROM node:20-slim

# System deps: Python, build tools for psycopg2/cryptography, SSL certs
RUN apt-get update && apt-get install -y \
    git curl procps psmisc \
    python3 python3-pip python3-venv \
    gcc libpq-dev \
    ca-certificates \
    vim \
    zsh \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Python venv with project dependencies (baked into image)
RUN python3 -m venv /opt/venv
COPY requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt
# PyTorch CPU-only (separate step to use the lightweight index)
RUN /opt/venv/bin/pip install --no-cache-dir torch \
    --index-url https://download.pytorch.org/whl/cpu
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH=/workspace/src

# Install Claude Code globally
RUN npm install -g @anthropic-ai/claude-code --unsafe-perm

# Non-root user (required for --dangerously-skip-permissions)
RUN useradd -m -s /bin/zsh claudeuser
WORKDIR /workspace
RUN chown -R claudeuser:claudeuser /workspace

USER claudeuser

RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended

CMD ["claude", "--dangerously-skip-permissions"]
