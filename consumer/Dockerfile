# 使用輕量級的 Python 3.11 映像檔
FROM python:3.11-slim

# 2. 設定環境變數
# 不寫入 .pyc 暫存檔，節省空間
ENV PYTHONDONTWRITEBYTECODE=1
# 強制 Python 直接輸出 Log，不放在緩衝區 (讓docker logs 可以直接到訊息)
ENV PYTHONUNBUFFERED=1

# 3. 設定容器內的工作目錄
WORKDIR /app

# 4. 先複製 requirements.txt
COPY requirements.txt .

# 5. 不裝任何 OS 系統套件，直接裝 Python 套件，並清除暫存！
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 6. 複製 Python 程式碼
COPY . .

# 7. 啟動 Agent
CMD ["python", "agent.py"]