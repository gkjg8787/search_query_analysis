FROM selenium/standalone-chromium:141.0

USER root

RUN apt-get update && \
    apt-get install -y tzdata
ENV TZ=Asia/Tokyo
RUN ln -sf /usr/share/zoneinfo/Japan /etc/localtime && \
    echo $TZ > /etc/timezone


RUN pip install uv
RUN apt-get install -y \
    procps 
RUN apt-get -y install locales && \
    localedef -f UTF-8 -i ja_JP ja_JP.UTF-8

ENV LANG=ja_JP.UTF-8 \
LANGUAGE=ja_JP:en \
LC_ALL=ja_JP.UTF-8

ENV DISPLAY=:99

WORKDIR /app
RUN mkdir /app/db && mkdir /app/log && mkdir /app/cookie

COPY requirements.txt ./

RUN uv venv /app/venv && . /app/venv/bin/activate && uv pip install -r requirements.txt


ENV PATH=/app/venv/bin:$PATH

COPY . .

EXPOSE 8130

WORKDIR /app/app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8130"]
