# 使用輕量級的 Python 3.11 映像檔
FROM python:3.11-slim

# 設定工作目錄
WORKDIR /app

# 先複製 requirements.txt 並安裝套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 將原始碼複製進容器
COPY main.py .

# 啟動應用程式
CMD ["python", "main.py"]