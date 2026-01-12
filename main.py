import os
import logging
import traceback
from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
import os
from dotenv import load_dotenv # 匯入套件
import uvicorn
load_dotenv() # 這一行會自動尋找並讀取 .env 檔案


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# --- 1. 環境變數讀取與檢查 ---
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, GOOGLE_API_KEY]):
    logger.error("❌ 嚴重錯誤: 缺少必要的環境變數，請檢查 Zeabur 設定！")

# Line 設定
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Google Gemini 設定
try:
    genai.configure(api_key=GOOGLE_API_KEY)
    # 建議加上 generation_config 限制回應長度，避免超時
    model = genai.GenerativeModel('gemini-3-flash-preview')

    
except Exception as e:
    logger.error(f"❌ Gemini 設定失敗: {e}")

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers['X-Line-Signature']
    body = await request.body()
    try:
        handler.handle(body.decode(), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text
    logger.info(f"收到訊息: {user_text}") # 記錄收到的訊息 

    # 呼叫 Gemini 進行分析
    analysis_result = get_psych_analysis(user_text)
    
    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=analysis_result)
        )
    except Exception as e:
        logger.error(f"❌ Line 回覆失敗: {e}")

def get_psych_analysis(text):
    # 設定 Prompt
    prompt = f"""
    你是一位心理學專家，請分析以下對話的潛台詞、情緒狀態以及說話者的心理需求。
    請用條列式回答，語氣溫暖且專業。
    
    待分析對話：
    {text}
    """
    
    try:
        # --- 2. 呼叫 Gemini 並加入錯誤處理 ---
        response = model.generate_content(prompt)
        
        # 檢查是否因安全設定被擋 (例如 Hate speech, Harassment)
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            logger.warning(f"⚠️ 內容被 Google 安全機制阻擋: {response.prompt_feedback}")
            return "抱歉，這段對話涉及敏感內容，我的安全機制無法進行分析。"

        # 確保有文字回傳
        if response.text:
            return response.text
        else:
            return "分析完成，但無法產生文字回應 (可能內容為空)。"

    # --- 3. 捕捉特定的 Google API 錯誤 ---
    except google_exceptions.InvalidArgument as e:
        logger.error(f"❌ 參數錯誤 (可能是 Model 名稱錯): {e}")
        return "系統設定錯誤 (Invalid Argument)。"
    except google_exceptions.Unauthenticated as e:
        logger.error(f"❌ API Key 錯誤或過期: {e}")
        return "系統認證失敗，請檢查 API Key。"
    except google_exceptions.ResourceExhausted as e:
        logger.error(f"❌ 免費額度用完或請求太快: {e}")
        return "目前系統繁忙，請稍後再試。"
    except Exception as e:
        # 這裡會印出你原本看到的 grpc 錯誤的完整細節
        logger.error(f"❌ Gemini 未知錯誤: {e}")
        logger.error(traceback.format_exc()) # 印出完整錯誤路徑
        return "AI 分析暫時無法使用，請通知管理員檢查 Log。"
    

    # 【新增 2】 在程式碼的最底端加入這一段
if __name__ == "__main__":
    # 雲端環境會自動分配 PORT，如果沒分配則預設使用 8080
    port = int(os.environ.get("PORT", 8080))
    # 這裡的 host 必須是 0.0.0.0
    uvicorn.run(app, host="0.0.0.0", port=port)