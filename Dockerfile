# Docker image (Hugging Face Spaces or any host): Streamlit web app + FFmpeg (libass captions, RNNoise, loudnorm)
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Spaces runs the app as user 1000: give it a home directory and write access
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .
# videos, results and AI models (face, segmentation, RNNoise) live here; models download on first use
RUN mkdir -p input output models

EXPOSE 7860
# XSRF/CORS off: Spaces shows the app inside an iframe, otherwise uploads fail with 403
CMD ["streamlit", "run", "server.py", "--server.port", "7860", "--server.address", "0.0.0.0", \
     "--server.headless", "true", "--server.enableXsrfProtection", "false", "--server.enableCORS", "false"]
