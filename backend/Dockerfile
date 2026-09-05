# Sentinel API and ANPR worker.
#
# The ONNX models are downloaded at build time so a container starts without
# reaching out to the network, and so the first inference is not delayed by a
# cold cache.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# libGL and libglib are required by OpenCV; ffmpeg provides the RTSP decoders.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Warm the model cache during the build.
RUN python -c "from fast_alpr import ALPR; ALPR(detector_model='yolo-v9-t-384-license-plate-end2end', ocr_model='cct-s-v2-global-model')"

COPY . .

# Run as an unprivileged user; the evidence volume is the only writable path.
RUN useradd --create-home --uid 10001 sentinel \
    && mkdir -p /data/evidence \
    && chown -R sentinel:sentinel /app /data
USER sentinel

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
