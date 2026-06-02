FROM node:20-slim

# Install necessary system utilities
RUN apt-get update && apt-get install -y git curl procps psmisc \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Claude Code globally but allow non-root execution
RUN npm install -g @anthropic-ai/claude-code --unsafe-perm

# Create a non-root user and setup the workspace
RUN useradd -m -s /bin/bash claudeuser
WORKDIR /workspace
RUN chown -R claudeuser:claudeuser /workspace

# Switch context to the unprivileged user
USER claudeuser

CMD ["bash"]

