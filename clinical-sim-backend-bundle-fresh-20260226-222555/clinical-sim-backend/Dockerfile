# Multi-stage Dockerfile for MedSim
# Stage 1: Build React frontend
# Stage 2: Python backend with pre-built frontend

# --- Stage 1: Frontend build ---
FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY frontend-react/package.json frontend-react/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend-react/ ./
RUN npx vite build

# --- Stage 2: Python backend ---
FROM python:3.11-slim AS backend

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e "." 2>/dev/null || pip install --no-cache-dir .

# Copy application code
COPY app/ ./app/

# Copy pre-built frontend from stage 1
COPY --from=frontend-build /build/../frontend-dist/ ./frontend-dist/
# Also keep the legacy HTML frontend
COPY frontend/ ./frontend/

# Create data directories
RUN mkdir -p app/data/sessions

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Environment defaults
ENV HOST=0.0.0.0
ENV PORT=8000
ENV APP_ENV=production
ENV DATABASE_URL=sqlite:///./medsim.db

EXPOSE 8000

# Run with uvicorn
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
