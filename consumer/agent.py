import json
import os
import logging
from psycopg2 import pool
import time
from confluent_kafka import Consumer, Producer, KafkaError
import google.generativeai as genai

# 1. 設定高品質日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# 全域變數：用來統計總 Token 消耗量
TOTAL_TOKENS_USED = 0

# ==========================================
# 模組 1: 資料庫讀取 
# ==========================================
class PolicyDatabase:
    """將資料庫操作封裝成類別，這讓我們未來可以輕易替換成 MockDB 來做單元測試"""
    def __init__(self, host, dbname, user, password):
        self.pool = pool.SimpleConnectionPool(
            minconn=1,
            maxconn=5,# 最多同時 5 條連線
            host=host,
            database=dbname,
            user=user,
            password=password
        )

    def query(self, policy_id: str) -> str:
        """
        當你需要查詢特定保單的詳細資訊、狀態、險種或保額時，請呼叫此工具。
        傳入參數 policy_id 必須是字串格式 (例如 'TX-9981')。
        """
        logging.info(f"🛠️ [Tool 執行] 正在查詢資料庫，保單號碼: {policy_id}")
        conn = self.pool.getconn()  # 從 pool 借一條連線
        try:
            cur = conn.cursor()
            cur.execute("SELECT status, policy_type, coverage_amount FROM policies WHERE policy_id = %s", (policy_id,))
            row = cur.fetchone()
            cur.close()
            
            if row:
                return f"查詢成功。保單狀態: {row[0]}, 險種: {row[1]}, 保額: {row[2]}"
            return "資料庫中找不到此保單號碼。"
        except Exception as e:
            return f"資料庫查詢發生錯誤: {str(e)}"
        finally:
            self.pool.putconn(conn) # 一定要還回去，不管成功或失敗

# ==========================================
# 模組 2: Agent 核心邏輯 (與 Kafka 完全獨立)
# ==========================================
class InsuranceAgent:
    """Agent 只負責思考，它不知道資料從哪來(Kafka)，也不知道資料庫長怎樣"""
    def __init__(self, api_key: str, db_tool):
        if not api_key:
            raise ValueError("請確認已設定 GEMINI_API_KEY 環境變數！")
            
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name='models/gemini-2.5-flash',
            tools=[db_tool.query],
            system_instruction="你是一個專業的保險理賠與客服 AI 助理。請根據使用者的指示完成任務。如果有保單號碼，你必須先使用工具查詢保單狀態後再做回答。"
        )

    def process(self, instruction: str, task_id: str) -> str:
        global TOTAL_TOKENS_USED
        logging.info(f"🤖 [Agent 思考中] 開始處理任務 {task_id}: {instruction}")

        MAX_RETRIES = 3

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                chat = self.model.start_chat(enable_automatic_function_calling=True)
                response = chat.send_message(instruction)

                # --- Cost Awareness ---
                prompt_tokens = response.usage_metadata.prompt_token_count #送進去的
                candidate_tokens = response.usage_metadata.candidates_token_count  # AI 生成的
                total_tokens = response.usage_metadata.total_token_count
                TOTAL_TOKENS_USED += total_tokens
                logging.info(f"💰 [Token 成本統計] 本次任務: {total_tokens} (Prompt: {prompt_tokens}, 生成: {candidate_tokens}) | 系統累計總用量: {TOTAL_TOKENS_USED} tokens")

                return response.text.strip()  # 成功就直接回傳，不繼續 retry

            except Exception as e:
                error_msg = str(e)
                if '429' in error_msg or 'quota' in error_msg.lower():
                    wait = 60 * attempt  # 第1次60秒、第2次120秒、第3次180秒
                    logging.warning(f"⚠️ 429 Rate Limit (第 {attempt}/{MAX_RETRIES} 次)，等待 {wait} 秒後重試...")
                    time.sleep(wait)
                    # loop 繼續，進入下一次 attempt
                else:
                    # 非 429 的錯誤，不需要 retry
                    logging.error(f"❌ Agent 處理失敗: {error_msg}")
                    raise  # 讓上層 main() 決定怎麼處理

        # 三次都失敗，raise 讓 main() 知道
        raise RuntimeError(f"任務 {task_id} 在 {MAX_RETRIES} 次重試後仍失敗")

# ==========================================
# 模組 3: main來整合DB, Agent , Kafka
# ==========================================
def main():
    logging.info("🚀 啟動 Agent Consumer...")
    
    # 1. 初始化資料庫依賴
    db = PolicyDatabase(
        host=os.getenv('DB_HOST', 'db'),
        dbname=os.getenv('DB_NAME', 'insurance_db'),
        user=os.getenv('DB_USER', 'user'),
        password=os.getenv('DB_PASS', 'password')
    )
    
    # 2. 初始化 Agent，注入 DB 工具
    agent = InsuranceAgent(api_key=os.getenv("GEMINI_API_KEY"), db_tool=db)
    
    # 3. 建立 DLQ 專用的 Producer
    dlq_producer = Producer({'bootstrap.servers': 'kafka:29092'})

    # 4. 初始化 Kafka Consumer
    consumer = Consumer({
        'bootstrap.servers': 'kafka:29092',
        'group.id': 'agent-group-1',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False # 手動 Commit，確保訊息不遺失 (Graceful failure)
    })
    consumer.subscribe(['incoming-requests'])

    try:
        while True:
            msg = consumer.poll(1.0)
            # 讓 DLQ Producer 在背景清理緩衝區，避免emory Leak
            dlq_producer.poll(0)
            
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                else:
                    logging.error(f"❌ Kafka 錯誤: {msg.error()}")
                    continue

            # 成功收到訊息，開始解析
            try:
                task_data = json.loads(msg.value().decode('utf-8'))
                instruction = task_data.get('instruction', '')
                task_id = task_data.get('task_id', 'Unknown')
                
                # 執行 Agent 邏輯
                final_answer = agent.process(instruction, task_id)
                
                if final_answer:
                    logging.info(f"✅ [Agent 處理完成] 最終回覆:\n{final_answer}\n" + "-"*50)
                
                # 處理完畢後，手動確認 (Commit) 訊息已完成
                consumer.commit(message=msg)
                
            except json.JSONDecodeError:
                logging.error("❌ 收到格式錯誤的訊息，送往 DLQ。")
                dlq_producer.produce(
                    topic='incoming-requests.DLQ',
                    value=msg.value(),  # 原始訊息原封不動送過去
                )
                # Commit 掉主線的壞訊息，讓系統繼續處理下一筆
                consumer.commit(message=msg)

            except RuntimeError as e:
                # 429 retry 三次失敗，不 commit，訊息留在 Kafka
                logging.error(f"❌ {e}，訊息不 commit")
            except Exception as e:
                # 其他未知錯誤，不 commit
                logging.error(f"❌ 未預期錯誤: {e}，訊息不 commit")

    except KeyboardInterrupt:
        logging.info("🛑 收到停止訊號，準備關閉 Consumer...")
    finally:
        #只有在系統真正要關閉時，才使用 flush 確保所有 DLQ 訊息都送達
        dlq_producer.flush()
        consumer.close()
        logging.info("👋 Consumer 安全關閉。")

if __name__ == '__main__':
    main()