FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app
COPY . /app

RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# 스크립트 파일명 맞춰줘 (예: version1.py / stock_watcher.py 등)
CMD ["python", "-u", "sony_script.py"]
