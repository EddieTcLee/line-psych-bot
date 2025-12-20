import os
from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai  # <--- 引入 Google 的庫

app = FastAPI()

# 設定環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# Line 設定
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Google Gemini 設定
genai.configure(api_key=GOOGLE_API_KEY)

# 修改後的寫法
model = genai.GenerativeModel('gemini-pro')

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
    
    # 呼叫 Gemini 進行分析
    analysis_result = get_psych_analysis(user_text)
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=analysis_result)
    )

def get_psych_analysis(text):
    # 設定 Prompt (提示詞)
    prompt = f"""
    你是一位心理學專家，請分析以下對話的潛台詞、情緒狀態以及說話者的心理需求。
    請用條列式回答，語氣溫暖且專業。
    
    待分析對話：
    {text}
    """
    
    # 呼叫 Gemini 生成內容
    response = model.generate_content(prompt)
    return response.text