FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY attendee_information24.py arrival_review_v2.py app.py expense_notes.py reminder17.py reminder21.py reminder23.py test_reminder17.py ./
COPY static ./static
ENV BNI_EVENT_DATA_DIR=/data
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 30 app:app"]
