FROM python:3.6

# Install Docker binaries inside the container
RUN apt-get update && \
    apt-get -y install apt-transport-https \
        ca-certificates \
        curl \
        gnupg2 \
        software-properties-common && \
    curl -fsSL https://download.docker.com/linux/$(. /etc/os-release; echo "$ID")/gpg > /tmp/dkey && \
    apt-key add /tmp/dkey && \
    add-apt-repository \
        "deb [arch=amd64] https://download.docker.com/linux/$(. /etc/os-release; echo "$ID") \
        $(lsb_release -cs) \
        stable" && \
    apt-get update && \
    apt-get -y install docker-ce


COPY requirements.txt /tmp/requirements.txt
COPY requirements-dev.txt /tmp/requirements-dev.txt
# RUN ls -l
RUN pip install -r /tmp/requirements.txt
RUN pip install -r /tmp/requirements-dev.txt

WORKDIR "/var/regovar_app"
CMD ["python regovar.py"]
