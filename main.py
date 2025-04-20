from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import TextMessage
from linebot.v3.exceptions import InvalidSignatureError
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, time, timedelta
import re
import threading
import requests
import time as time_module
import openai
from typing import Optional, Dict, Any
from zoneinfo import ZoneInfo
import dateparser

# 環境変数の読み込み
load_dotenv()

# OpenAIの設定
openai.api_key = os.getenv('OPENAI_API_KEY')

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

# スリープ防止のための自己ping
RENDER_URL = os.getenv('RENDER_URL')
PORT = int(os.getenv('PORT', 10000))

# タイムゾーンの設定
JST = ZoneInfo('Asia/Tokyo')

def get_current_jst_date() -> datetime:
    """現在の日本時間を返す"""
    return datetime.now(JST)

def keep_alive():
    while True:
        try:
            if RENDER_URL:
                requests.get(RENDER_URL)
                print("Ping sent successfully")
        except Exception as e:
            print(f"Ping failed: {str(e)}")
        time_module.sleep(60)  # 1分ごとにping

@app.on_event("startup")
async def startup_event():
    if RENDER_URL:
        thread = threading.Thread(target=keep_alive, daemon=True)
        thread.start()
        print("Keep-alive thread started")

@app.get("/")
async def root():
    return {"message": "LINE Task Management Bot is running!"}

def get_system_prompt() -> str:
    """システムプロンプトを返す"""
    return """あなたはタスク管理アシスタントです。ユーザーのメッセージを解析し、以下のアクションを判断してください：

1. タスクの登録
2. タスクの完了
3. タスク一覧の表示
4. 特定の日付のタスク一覧表示
5. リマインドの設定

応答は以下のJSON形式で返してください：
{
    "action": "register" | "complete" | "list" | "list_date" | "remind",
    "task_content": "タスクの内容",
    "date": "日付（YYYY-MM-DD形式）",
    "time": "時間（HH:MM形式）",
    "remind_time": "リマインド時間（HH:MM形式）"
}

日付や時間が指定されていない場合は、nullを返してください。
タスク一覧の表示の場合は、dateに表示したい日付を指定してください。
リマインドの設定の場合は、remind_timeにリマインドしたい時間を指定してください。
"""

def process_message_with_llm(message: str) -> Dict[str, Any]:
    """LLMを使用してメッセージを処理し、アクションを判断する"""
    try:
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": get_system_prompt()},
                {"role": "user", "content": message}
            ],
            temperature=0.3
        )
        
        # 応答をJSONとして解析
        import json
        result = json.loads(response.choices[0].message.content)
        
        # 日付の解析を改善
        if result.get('date'):
            parsed_date = dateparser.parse(result['date'], languages=['ja'])
            if parsed_date:
                result['date'] = parsed_date.strftime('%Y-%m-%d')
        
        return result
    except Exception as e:
        print(f"Error processing message with LLM: {str(e)}")
        return None

def handle_task_registration(user_id: str, task_content: str, date: str, time: str, remind_time: str = None) -> str:
    """タスクを登録する"""
    try:
        data = {
            'user_id': user_id,
            'content': task_content,
            'is_done': False,
            'scheduled_date': date,
            'scheduled_time': time,
            'remind_time': remind_time
        }
        
        supabase.table('tasks').insert(data).execute()
        
        # 日付と時刻の表示用文字列を作成
        current_date = get_current_jst_date().date()
        task_date = datetime.strptime(date, '%Y-%m-%d').date()
        date_str = '今日' if task_date == current_date else task_date.strftime('%m/%d')
        time_str = f' {time}' if time else ''
        remind_str = f'\nリマインド: {remind_time}' if remind_time else ''
        
        return f'タスクを登録しました:\n{date_str}{time_str} {task_content}{remind_str}'
    except Exception as e:
        return f'タスクの登録に失敗しました: {str(e)}'

def handle_task_completion(user_id: str, task_content: str) -> str:
    """タスクを完了にする"""
    try:
        supabase.table('tasks').update({'is_done': True}).eq('user_id', user_id).eq('content', task_content).execute()
        return f'タスクを完了しました: {task_content}'
    except Exception as e:
        return f'タスクの完了に失敗しました: {str(e)}'

def handle_task_list(user_id: str, date: str = None) -> str:
    """タスク一覧を表示する"""
    try:
        query = supabase.table('tasks').select('*').eq('user_id', user_id)
        if date:
            query = query.eq('scheduled_date', date)
        else:
            query = query.eq('scheduled_date', get_current_jst_date().date().isoformat())
        
        response = query.order('scheduled_time').execute()
        tasks = response.data
        
        if not tasks:
            current_date = get_current_jst_date().date()
            date_str = '今日' if not date else datetime.strptime(date, '%Y-%m-%d').date()
            date_str = '今日' if date_str == current_date else date_str.strftime('%m/%d')
            return f'{date_str}のタスクはありません'
        
        current_date = get_current_jst_date().date()
        task_date = current_date if not date else datetime.strptime(date, '%Y-%m-%d').date()
        date_str = '今日' if task_date == current_date else task_date.strftime('%m/%d')
        task_list = [f'【{date_str}のタスク】']
        for task in tasks:
            status = '✅' if task['is_done'] else '⏳'
            time_str = f"{task['scheduled_time']} " if task['scheduled_time'] else ''
            task_list.append(f"{status} {time_str}{task['content']}")
        
        return '\n'.join(task_list)
    except Exception as e:
        return f'タスク一覧の取得に失敗しました: {str(e)}'

def handle_reminder(user_id: str, date: str, time: str) -> str:
    """指定された日時のタスクをリマインドする"""
    try:
        query = supabase.table('tasks').select('*').eq('user_id', user_id).eq('scheduled_date', date)
        if time:
            query = query.eq('scheduled_time', time)
        
        response = query.execute()
        tasks = response.data
        
        if not tasks:
            return f'{date} {time if time else ""}の予定はありません'
        
        task_list = [f'【{date} {time if time else ""}の予定】']
        for task in tasks:
            task_list.append(f"・{task['content']}")
        
        return '\n'.join(task_list)
    except Exception as e:
        return f'予定の取得に失敗しました: {str(e)}'

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
    
    # LLMでメッセージを処理
    result = process_message_with_llm(message)
    
    if not result:
        line_bot_api.reply_message_with_http_info(
            {
                'replyToken': event.reply_token,
                'messages': [TextMessage(text='申し訳ありません。メッセージの処理に失敗しました。もう一度お試しください。')]
            }
        )
        return
    
    # アクションに応じて処理
    try:
        response_text = ""
        if result['action'] == 'register':
            if not result.get('task_content'):
                raise ValueError("タスクの内容が指定されていません")
            response_text = handle_task_registration(user_id, result['task_content'], result['date'], result['time'], result.get('remind_time'))
        elif result['action'] == 'complete':
            if not result.get('task_content'):
                raise ValueError("完了するタスクが指定されていません")
            response_text = handle_task_completion(user_id, result['task_content'])
        elif result['action'] == 'list':
            response_text = handle_task_list(user_id)
        elif result['action'] == 'list_date':
            response_text = handle_task_list(user_id, result['date'])
        elif result['action'] == 'remind':
            response_text = handle_reminder(user_id, result['date'], result['time'])
        else:
            raise ValueError("不明なアクションです")
        
        # 応答テキストが空の場合はエラーメッセージを設定
        if not response_text:
            response_text = "申し訳ありません。処理中にエラーが発生しました。もう一度お試しください。"
        
        line_bot_api.reply_message_with_http_info(
            {
                'replyToken': event.reply_token,
                'messages': [TextMessage(text=response_text)]
            }
        )
    except Exception as e:
        print(f"Error in handle_message: {str(e)}")
        line_bot_api.reply_message_with_http_info(
            {
                'replyToken': event.reply_token,
                'messages': [TextMessage(text=f"申し訳ありません。エラーが発生しました: {str(e)}")]
            }
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT) 