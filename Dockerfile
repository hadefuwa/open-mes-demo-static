FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
WORKDIR /srv/app

# Collect the admin site's static files at build time (no database or real secrets needed).
RUN SECRET_KEY=build-only DEBUG=0 python manage.py collectstatic --noinput

EXPOSE 8000
# Apply any new migrations, then serve. PORT is set by the host (Render); 8000 otherwise.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi --bind 0.0.0.0:${PORT:-8000} --workers 2 --access-logfile -"]
