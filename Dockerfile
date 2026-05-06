FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cr_learner/ ./cr_learner/
COPY pyproject.toml .

RUN pip install --no-cache-dir --no-deps -e .

CMD ["cr-learner", "--help"]
