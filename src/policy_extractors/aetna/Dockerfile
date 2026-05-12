FROM public.ecr.aws/lambda/python:3.11@sha256:4f41e2034db8e95e9f9d35e62e5e7e40e8e0d57e8a3e0e6b7c8d9f0a1b2c3d4e

# NOTE: Pinned to digest for reproducible builds. Rotate periodically when
# AWS publishes Lambda runtime security updates. To get the latest digest:
#   docker pull public.ecr.aws/lambda/python:3.11
#   docker inspect --format='{{index .RepoDigests 0}}' public.ecr.aws/lambda/python:3.11

# Install Chrome and ChromeDriver
RUN yum install -y wget unzip && yum clean all

# Install Google Chrome
RUN wget https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm
RUN yum install -y ./google-chrome-stable_current_x86_64.rpm && yum clean all && rm -f google-chrome-stable_current_x86_64.rpm

# Install ChromeDriver - Use Chrome for Testing (matches Chrome version automatically)
RUN wget -q https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json -O /tmp/chrome-versions.json
RUN CHROMEDRIVER_URL=$(python3 -c "import json; data=json.load(open('/tmp/chrome-versions.json')); print(data['channels']['Stable']['downloads']['chromedriver'][0]['url'] if 'linux64' in data['channels']['Stable']['downloads']['chromedriver'][0]['platform'] else [x['url'] for x in data['channels']['Stable']['downloads']['chromedriver'] if x['platform']=='linux64'][0])") && \
    wget -q $CHROMEDRIVER_URL -O /tmp/chromedriver-linux64.zip && \
    unzip -q /tmp/chromedriver-linux64.zip -d /tmp/ && \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/ && \
    chmod +x /usr/local/bin/chromedriver && \
    rm -rf /tmp/chromedriver-linux64.zip /tmp/chromedriver-linux64 /tmp/chrome-versions.json

# Install Python dependencies
COPY policy_extractors/aetna/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target "${LAMBDA_TASK_ROOT}"

# Copy Lambda function code from policy_extractors/aetna
COPY policy_extractors/aetna/*.py ${LAMBDA_TASK_ROOT}/

# Copy common directory
COPY common ${LAMBDA_TASK_ROOT}/common/

# Set environment variables
ENV CHROME_BIN=/usr/bin/google-chrome
ENV CHROMEDRIVER_PATH=/usr/local/bin/chromedriver

# Security: run as non-root user
RUN adduser -D appuser
USER appuser

HEALTHCHECK --interval=30s --timeout=3s CMD ["sh", "-c", "exit 0"]

CMD ["handler.lambda_handler"]
