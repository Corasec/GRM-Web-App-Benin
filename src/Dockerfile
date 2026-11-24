FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir --upgrade pip

# create app directory.
RUN mkdir -p /usr/appserver
WORKDIR /usr/appserver

# install production requirements (dev/test tools are in requirements.dev.txt)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy all the code
COPY . .

EXPOSE 9000

ENTRYPOINT [ "./run.sh" ]

CMD [ "serve" ]
