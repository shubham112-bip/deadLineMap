FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir gunicorn==23.0.0

COPY app/app.py ./app.py
COPY gunicorn.conf.py ./gunicorn.conf.py

CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:application"]
