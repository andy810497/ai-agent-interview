import json
import os
import logging
import psycopg2
import time
from confluent_kafka import Consumer, KafkaError
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
        self.config = {'host': host, 'database': dbname, 'user': user, 'password': password}

    def query(self, policy_id: str) -> str:
        """
        當你需要查詢特定保單的詳細資訊、狀態、險種或保額時，請呼叫此工具。
        傳入參數 policy_id 必須是字串格式 (例如 'TX-9981')。
        """
        logging.info(f"🛠️ [Tool 執行] 正在查詢資料庫，保單號碼: {policy_id}")
        try:
            conn = psycopg2.connect(**self.config)
            cur = conn.cursor()
            cur.execute("SELECT status, policy_type, coverage_amount FROM policies WHERE policy_id = %s", (policy_id,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            
            if row:
                return f"查詢成功。保單狀態: {row[0]}, 險種: {row[1]}, 保額: {row[2]}"
            return "資料庫中找不到此保單號碼。"
        except Exception as e:
            return f"資料庫查詢發生錯誤: {str(e)}"

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
        
        chat = self.model.start_chat(enable_automatic_function_calling=True)
        
        try:
            response = chat.send_message(instruction)
            
            # --- Cost Awareness ---
            prompt_tokens = response.usage_metadata.prompt_token_count
            candidate_tokens = response.usage_metadata.candidates_token_count
            total_tokens = response.usage_metadata.total_token_count
            TOTAL_TOKENS_USED += total_tokens
            
            logging.info(f"💰 [Token 成本統計] 本次任務: {total_tokens} (Prompt: {prompt_tokens}, 生成: {candidate_tokens}) | 系統累計總用量: {TOTAL_TOKENS_USED} tokens")
            
            return response.text.strip()
            
        except Exception as e:
            error_msg = str(e)
            if '429' in error_msg or 'quota' in error_msg.lower():
                logging.warning("⚠️ 觸發 API 額度限制 (429 Rate Limit)！系統將強制暫停 60 秒後再繼續處理佇列...")
                time.sleep(60)
                return "系統因 API 限制暫停處理，請稍後再試。"
            else:
                logging.error(f"❌ Agent 處理失敗: {error_msg}")
                return f"處理發生錯誤: {error_msg}"

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
    
    # 3. 初始化 Kafka Consumer
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
                logging.error("❌ 收到格式錯誤的訊息，跳過處理。")
                consumer.commit(message=msg) # 壞掉的訊息也要 commit 掉，以免卡死

    except KeyboardInterrupt:
        logging.info("🛑 收到停止訊號，準備關閉 Consumer...")
    finally:
        consumer.close()
        logging.info("👋 Consumer 安全關閉。")

if __name__ == '__main__':
    main()