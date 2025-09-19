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
COPY ./setup_alias.sh /etc/profile.d
COPY ./ics /app/ics

# Add ailas commands to .bashrc for non-login shell
RUN cat /etc/profile.d/setup_alias.sh > /root/.bashrc

# Create required directories
RUN mkdir -p  /app/data/res /app/data/log

# Set the default command for the container
CMD ["python", "/app/ics/icsd.py"]
