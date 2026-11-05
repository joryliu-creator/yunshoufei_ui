FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

WORKDIR /opt/cloud-billing-ui-automation

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

CMD ["python", "scripts/run_jenkins_regression.py", "--test-env", "standard1", "--max-minutes", "0", "--junit"]
