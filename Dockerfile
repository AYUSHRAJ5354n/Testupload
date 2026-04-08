FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

# Create local ffmpeg alias (NO CODE CHANGE NEEDED)
RUN ln -s /usr/bin/ffmpeg ./ffmpeg

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "bot.py"]
