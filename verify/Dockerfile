FROM python:3.12-slim

WORKDIR /verify

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 一次性验收：跑完即退出，退出码即验收结果
CMD ["pytest", "-v", "--tb=short"]
