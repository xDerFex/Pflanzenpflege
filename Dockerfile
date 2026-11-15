FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BIND=0.0.0.0 PORT=8000 DATA_DIR=/data
WORKDIR /app
COPY server.py /app/server.py
COPY static /app/static
RUN useradd --uid 10001 --create-home plant && mkdir /data && chown plant:plant /data
USER plant
VOLUME /data
EXPOSE 8000
CMD ["python", "server.py"]
