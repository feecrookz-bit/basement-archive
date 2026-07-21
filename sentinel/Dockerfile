FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY schema.sql config.yaml ./
COPY data ./data
COPY sentinel ./sentinel
CMD ["python", "-m", "sentinel", "run"]
