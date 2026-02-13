FROM python:3.13-slim-trixie

RUN pip install uv

RUN apt-get update && \
    apt-get install -y tzdata
ENV TZ=Asia/Tokyo
RUN ln -sf /usr/share/zoneinfo/Japan /etc/localtime && \
    echo $TZ > /etc/timezone


RUN apt-get install -y \
    sqlite3 procps curl gnupg apt-transport-https xvfb
RUN apt-get -y install locales && \
    localedef -f UTF-8 -i ja_JP ja_JP.UTF-8

ENV LANG=ja_JP.UTF-8 \
LANGUAGE=ja_JP:en \
LC_ALL=ja_JP.UTF-8

RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
RUN echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list

ENV DISPLAY=:99

RUN apt update && apt install -y google-chrome-stable

WORKDIR /app
RUN mkdir /app/db && mkdir /app/log && mkdir /app/cookie

COPY requirements.txt ./

RUN uv venv /app/venv && . /app/venv/bin/activate && uv pip install -r requirements.txt

ENV PATH=/app/venv/bin:$PATH

COPY . .

EXPOSE 8130

WORKDIR /app/app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8130"]
