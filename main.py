import os
import logging
import traceback
import io
from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from dotenv import load_dotenv
import uvicorn
from PIL import Image # 處理圖片用

load_dotenv()

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
    # 使用 Flash 模型，它讀圖速度快且便宜
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

# --- 處理文字訊息 ---
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_text = event.message.text
    logger.info(f"收到文字訊息: {user_text}")
    
    # 呼叫分析函式 (只傳文字)
    reply_text = get_advice(text=user_text, image=None)
    reply_line(event.reply_token, reply_text)

# --- 處理圖片訊息 (截圖分析) ---
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    logger.info(f"收到圖片訊息 ID: {event.message.id}")
    
    try:
        # 1. 從 Line 伺服器取得圖片內容
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = io.BytesIO(message_content.content)
        img = Image.open(image_bytes) # 轉成 PIL Image 格式
        
        # 2. 呼叫分析函式 (傳送圖片)
        reply_text = get_advice(text="請分析這張對話截圖", image=img)
        reply_line(event.reply_token, reply_text)
        
    except Exception as e:
        logger.error(f"❌ 圖片處理失敗: {e}")
        reply_line(event.reply_token, "抱歉，我無法讀取這張圖片，請稍後再試。")

def reply_line(token, text):
    try:
        line_bot_api.reply_message(token, TextSendMessage(text=text))
    except Exception as e:
        logger.error(f"❌ Line 回覆失敗: {e}")

def get_advice(text, image=None):
    # --- 修改重點：優化 Prompt 與格式規範 ---
    prompt_text = """
    你是一位高情商的心理學溝通專家。使用者會提供一段「對話文字」或「對話截圖」。
    請從心理學角度深入分析字裡行間的動機與情緒。

    【輸出格式規範 - 嚴格遵守】
    1. 嚴格禁止 Markdown：不要使用 #, **, ---, ``` 等符號，因為 LINE 無法顯示。
    2. LINE 友善排版：手機螢幕窄，請善用換行與空行。
    3. 標題與重點：使用 Emoji (如 🔍, 💡, ✅) 作為標題開頭。重點可用「」或【】包起來。
    4. 語氣：專業、溫暖、有洞察力。

    【請依照以下結構回答】
    
    🔍 心理潛台詞分析
    (分析對方的真實情緒、防禦機制或隱藏意圖，請使用心理學名詞如「防禦性模糊」、「正向增強」等並解釋)

    ⚠️ 風險提示
    (這段對話有沒有隱藏的地雷、誤會或情緒勒索的跡象)

    💡 下一步建議
    (具體行動建議，包含心理學策略，如鏡像效應等)

    💬 推薦回覆
    (請給我 2~3 個不同風格的回覆範例，例如：幽默版、誠懇版、高冷版)
    """
    
    inputs = [prompt_text]
    
    # 如果有圖片，就放圖片；如果有文字，就放文字
    if image:
        inputs.append(image)
    if text:
        inputs.append(text)

    try:
        response = model.generate_content(inputs)
        
        if response.text:
            # --- 修改重點：Python 端強制清洗格式 ---
            # 即使 Prompt 說了，AI 有時還是會加 **，這裡直接取代掉
            clean_text = response.text.replace("**", "").replace("##", "").replace("###", "").replace("---", "")
            return clean_text
        else:
            return "分析完成，但沒有產生文字回應。"

    except Exception as e:
        logger.error(f"❌ Gemini 分析錯誤: {e}")
        return "AI 目前忙碌中，請稍後再試。"
    # 設定超強 Prompt：包含分析與後續建議
    prompt_text = """
    你是一位高情商的溝通專家。使用者會提供一段「對話文字」或「對話截圖」。
    請針對內容進行以下分析：

    1. 🎯 核心分析：對方目前的真實情緒、潛台詞是什麼？
    2. ⚠️ 風險提示：這段對話有沒有隱藏的地雷或誤會？
    3. 💡 後續建議：我現在該怎麼做？請提供具體的行動建議。
    4. 💬 推薦回覆：請給我 2~3 個不同風格的回覆範例（例如：幽默版、誠懇版、高冷版）。

    請用溫暖、條理分明、簡短的語氣回答。
    """
    
    inputs = [prompt_text]
    
    # 如果有圖片，就放圖片；如果有文字，就放文字 (可以同時放)
    if image:
        inputs.append(image)
    if text:
        inputs.append(text)

    try:
        response = model.generate_content(inputs)
        
        if response.text:
            return response.text
        else:
            return "分析完成，但沒有產生文字回應。"

    except Exception as e:
        logger.error(f"❌ Gemini 分析錯誤: {e}")
        return "AI 目前忙碌中，請稍後再試。"

if __name__ == "__main__":
    # 自動讀取雲端環境變數 PORT，若無則用 8080 (方便本機測試)
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)