FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./app.py
RUN mkdir -p /app/templates
COPY AXA-Informe-Medico-GMM-FEB22.pdf ./templates/AXA-Informe-Medico-GMM-FEB22.pdf

RUN mkdir -p /app/generated
ENV GENERATED_DIR=/app/generated

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
