FROM python:3.12

# Set environment variables
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Set the working directory
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt /app/requirements.txt
RUN pip3 install -r requirements.txt

# Copy application scripts and resources
COPY ./setup_alias.sh /app
COPY ./ics /app/ics
COPY ./test_lab/test /app/test
COPY ./examples /app/examples

# Create required directories
RUN mkdir -p  /app/data/res /app/data/log

# Set the default command for the container
CMD ["python", "/app/ics/icsd.py"]
