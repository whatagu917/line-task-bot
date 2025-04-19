from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import TextMessage
from linebot.v3.exceptions import InvalidSignatureError
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, time
import re

# 環境変数の読み込み
load_dotenv()

# LINE Botの設定
configuration = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
client = ApiClient(configuration)
line_bot_api = MessagingApi(client)

# Supabaseの設定
# サービスロールキーを使用してRLSをバイパス
supabase: Client = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY', os.getenv('SUPABASE_KEY'))  # サービスロールキーがない場合は通常のキーを使用
)

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "LINE Task Management Bot is running!"}

def parse_task_message(message: str) -> tuple[str, time | None]:
    """タスクメッセージを解析して、タスク内容と時間を返す"""
    time_pattern = r'(\d{1,2}:\d{2})'
    time_match = re.search(time_pattern, message)
    
    if time_match:
        task_time = datetime.strptime(time_match.group(1), '%H:%M').time()
        task_content = re.sub(time_pattern, '', message).strip()
    else:
        task_time = None
        task_content = message.strip()
    
    return task_content, task_time

@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get('X-Line-Signature', '')
    body = await request.body()
    body_str = body.decode()
    
    try:
        handler.handle(body_str, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    message = event.message.text
    
    if message.startswith('タスク'):
        # タスク登録処理
        task_content, task_time = parse_task_message(message[3:].strip())
        
        data = {
            'user_id': user_id,
            'content': task_content,
            'is_done': False,
            'scheduled_date': datetime.now().date().isoformat(),
            'scheduled_time': task_time.strftime('%H:%M') if task_time else None
        }
        
        supabase.table('tasks').insert(data).execute()
        line_bot_api.reply_message_with_http_info(
            {
                'replyToken': event.reply_token,
                'messages': [TextMessage(text=f'タスクを登録しました: {task_content}')]
            }
        )
    
    elif message.startswith('完了'):
        # タスク完了処理
        task_content = message[3:].strip()
        supabase.table('tasks').update({'is_done': True}).eq('user_id', user_id).eq('content', task_content).execute()
        line_bot_api.reply_message_with_http_info(
            {
                'replyToken': event.reply_token,
                'messages': [TextMessage(text=f'タスクを完了しました: {task_content}')]
            }
        )
    
    elif message in ['リスト', '今日のタスク']:
        # タスク一覧表示
        today = datetime.now().date().isoformat()
        response = supabase.table('tasks').select('*').eq('user_id', user_id).eq('scheduled_date', today).order('scheduled_time').execute()
        tasks = response.data
        
        if not tasks:
            line_bot_api.reply_message_with_http_info(
                {
                    'replyToken': event.reply_token,
                    'messages': [TextMessage(text='今日のタスクはありません')]
                }
            )
        else:
            task_list = ['【今日のタスク】']
            for task in tasks:
                status = '✅' if task['is_done'] else '⏳'
                time_str = f"{task['scheduled_time']} " if task['scheduled_time'] else ''
                task_list.append(f"{status} {time_str}{task['content']}")
            
            line_bot_api.reply_message_with_http_info(
                {
                    'replyToken': event.reply_token,
                    'messages': [TextMessage(text='\n'.join(task_list))]
                }
            )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 