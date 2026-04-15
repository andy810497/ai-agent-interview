import json
import time
import random
import logging
from confluent_kafka import Producer

# 設定高質感的 Log 輸出格式
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# Kafka 設定 (注意：因為是在 Docker network 內，所以連線 kafka:29092)
KAFKA_BROKER = 'kafka:29092'
TOPIC_NAME = 'incoming-requests'

def delivery_report(err, msg):
    """
    Kafka 是非同步的，我們必須有這個機制來確認訊息到底是成功送達還是失敗。
    """
    if err is not None:
        logging.error(f'❌ 訊息發送失敗: {err}')
    else:
        logging.info(f'✅ 成功發送任務到 Topic [{msg.topic()}] (Partition: {msg.partition()})')

def generate_mock_task():
    """模擬產生各種客服進線或理賠任務"""
    task_types = ['policy_inquiry', 'claim_processing', 'technical_support']
    
    # 建立一個充滿真實感的假資料庫情境
    scenarios = [
        # 1. 正常情境
        {"type": "policy_inquiry", "instruction": "幫我查詢壽險保單號碼 TX-9981 的目前狀態。"},
        # 2. Edge Case A: 資訊完全缺失且語氣急迫
        {"type": "edge_case_missing_info", "instruction": "我剛剛在十字路口出車禍了，車頭全毀！你們保險公司趕快派人來處理然後賠錢給我！"},
        # 3. Edge Case B: 給予不存在的假號碼
        {"type": "edge_case_bad_data", "instruction": "請幫我查一下保單號碼 FAKE-9999 的理賠進度。"},
    ]
    
    task = random.choice(scenarios)
    task["task_id"] = f"TASK-{random.randint(1000, 9999)}"
    task["timestamp"] = time.time()
    return task

def main():
    logging.info("🚀 啟動 Kafka Producer 模擬器...")
    
    # 初始化 Producer
    producer_config = {
        'bootstrap.servers': KAFKA_BROKER,
        'client.id': 'mock-agent-producer'
    }
    producer = Producer(producer_config)

    try:
        while True:
            # 1. 產生一個假任務
            task = generate_mock_task()
            
            # 2. 將 Python 字典轉成 JSON 字串，並編碼成 bytes
            json_payload = json.dumps(task, ensure_ascii=False).encode('utf-8')
            
            # 3. 發送訊息到 Kafka
            logging.info(f"準備發送任務: {task['instruction']}")
            producer.produce(
                topic=TOPIC_NAME,
                value=json_payload,
                callback=delivery_report # 綁定剛剛寫好的 callback
            )
            
            # 4. 呼叫 poll 讓 callback 有機會被執行
            producer.poll(0)
            
            # 休息 10 到 20 秒再送下一筆，模擬真實流量，才不會一下把 Token 燒光
            sleep_time = random.randint(10, 20)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        logging.info("🛑 收到停止訊號，準備關閉 Producer...")
    finally:
        # 確保所有還在排隊的訊息都被送出
        producer.flush()
        logging.info("👋 Producer 安全關閉。")

if __name__ == '__main__':
    main()