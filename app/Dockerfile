FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --break-system-packages || \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# main.py is added in the final step (scheduler/orchestration).
# Until then this container is built and tested interactively per step.
CMD ["python", "main.py"]
