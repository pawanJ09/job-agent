# Pinned to 3.11 on purpose: the pinned dependency versions in requirements.txt
# (notably psycopg2-binary) ship prebuilt wheels for 3.11. Newer Pythons like
# 3.14 have no wheel for that version, so pip tries to compile it from source
# and fails with "pg_config executable not found".
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
