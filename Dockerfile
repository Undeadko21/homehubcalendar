# --- сборка веб-интерфейса ---
FROM node:22.16.0-alpine@sha256:41e4389f3d988d2ed55392df4db1420ad048ae53324a8e2b7c6d19508288107e AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ARG GIT_SHA=""
ENV VITE_BUILD=$GIT_SHA
RUN npm run build

# --- бэкенд ---
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOMECAL_CONFIG=/config/config.yaml HOMECAL_DATA_DIR=/data HOMECAL_STATIC=/app/static \
    HOMECAL_APP_DIR=/app/android-release HOMECAL_MAC_DIR=/app/mac-release HOMECAL_IOS_DIR=/app/ios-release HOMECAL_VERSIONS_DIR=/app/versions
WORKDIR /app
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY backend/app ./app
COPY --from=ui /ui/dist ./static
COPY android/release ./android-release
COPY macos/release ./mac-release
COPY ios/release ./ios-release
# Версии из исходников — сторож сборок сравнивает их с тем, что реально раздаётся
COPY android/version.properties ./versions/android.properties
COPY macos/version.txt ./versions/macos.txt
COPY ios/version.txt ./versions/ios.txt
ARG GIT_SHA=""
ENV HOMECAL_BUILD=$GIT_SHA
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
