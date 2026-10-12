FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "a2a-sdk==0.2.10" "PyJWT[crypto]>=2.10.1,<3.0"
COPY app.py /app/app.py
CMD ["python", "/app/app.py"]
