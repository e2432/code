FROM python:3.11-slim
WORKDIR /work
COPY input/ /work/input/
COPY tools/ /work/tools/
RUN chmod +x /work/tools/check_submission.py
RUN mkdir -p /work/output
