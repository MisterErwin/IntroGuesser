FROM python:3.9-buster

WORKDIR /usr/src/app

COPY requirements.txt ./

RUN apt update
RUN apt-get update && apt-get install -y \
    ffmpeg \
 && rm -rf /var/lib/apt/lists/*


RUN pip install --no-cache-dir -r requirements.txt

COPY server.py ./

EXPOSE 8765

CMD [ "python", "./server.py" ]
