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

def get_current_jst_datetime() -> datetime:
    """現在の日本時間をdatetimeオブジェクトとして返す"""
    # システムの現在時刻を取得
    now = datetime.now()
    # タイムゾーン情報を付与
    now = now.replace(tzinfo=JST)
    print(f"get_current_jst_datetime: システム時刻 = {now}")
    return now

def get_current_jst_date() -> datetime:
    """現在の日本時間を返す"""
    return get_current_jst_datetime()

def get_current_jst_time() -> str:
    """現在の日本時間をHH:MM形式で返す"""
    return get_current_jst_datetime().strftime('%H:%M')

def format_jst_datetime(dt: datetime) -> str:
    """datetimeオブジェクトを日本時間の文字列に変換する"""
    return dt.astimezone(JST).strftime('%Y-%m-%d %H:%M')

def parse_date(date_str: str) -> datetime:
    """日付文字列を日本時間のdatetimeオブジェクトに変換する"""
    if not date_str:
        return get_current_jst_datetime()
    
    # 日本語の日付表現を処理
    current_datetime = get_current_jst_datetime()
    print(f"parse_date: 入力文字列: {date_str}")
    print(f"parse_date: 現在の日時: {current_datetime}")
    
    if date_str.lower() in ['今日', 'きょう', 'today']:
        print("parse_date: 今日として処理")
        return current_datetime
    elif date_str.lower() in ['明日', 'あした', 'あす', 'tomorrow']:
        print("parse_date: 明日として処理")
        # 現在の日付を取得し、時刻を0時に設定
        current_date = current_datetime.date()
        tomorrow_date = current_date + timedelta(days=1)
        tomorrow = datetime.combine(tomorrow_date, datetime.min.time(), tzinfo=JST)
        print(f"parse_date: 明日の日付: {tomorrow}")
        return tomorrow
    elif date_str.lower() in ['明後日', 'あさって', 'day after tomorrow']:
        print("parse_date: 明後日として処理")
        # 現在の日付を取得し、時刻を0時に設定
        current_date = current_datetime.date()
        day_after_tomorrow_date = current_date + timedelta(days=2)
        day_after_tomorrow = datetime.combine(day_after_tomorrow_date, datetime.min.time(), tzinfo=JST)
        print(f"parse_date: 明後日の日付: {day_after_tomorrow}")
        return day_after_tomorrow
    
    # その他の日付表現を解析
    print(f"parse_date: dateparserで解析を試みます: {date_str}")
    print(f"parse_date: 基準日時: {current_datetime}")
    
    # 日付文字列がYYYY-MM-DD形式の場合
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        try:
            year, month, day = map(int, date_str.split('-'))
            parsed_date = datetime(year, month, day, tzinfo=JST)
            print(f"parse_date: YYYY-MM-DD形式として解析: {parsed_date}")
            return parsed_date
        except ValueError:
            print("parse_date: YYYY-MM-DD形式の解析に失敗")
    
    parsed_date = dateparser.parse(
        date_str,
        languages=['ja'],
        settings={
            'RELATIVE_BASE': current_datetime,
            'PREFER_DATES_FROM': 'future',
            'RETURN_AS_TIMEZONE_AWARE': True,
            'TIMEZONE': 'Asia/Tokyo'
        }
    )
    
    print(f"parse_date: dateparserの解析結果: {parsed_date}")
    
    if parsed_date:
        print(f"parse_date: 解析された日付: {parsed_date}")
        # タイムゾーンを日本時間に設定
        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=JST)
        else:
            parsed_date = parsed_date.astimezone(JST)
        print(f"parse_date: タイムゾーン設定後: {parsed_date}")
        
        # 日付が過去の場合は翌日に設定
        if parsed_date.date() < current_datetime.date():
            print(f"parse_date: 過去の日付を翌日に設定: {parsed_date.date()} -> {parsed_date.date() + timedelta(days=1)}")
            parsed_date = parsed_date + timedelta(days=1)
        
        return parsed_date
    
    # 日付が解析できない場合は今日の日付を使用
    print("parse_date: 日付が解析できないため今日の日付を使用")
    return current_datetime

def keep_alive():
    while True:
        try:
            if RENDER_URL:
                response = requests.get(RENDER_URL, timeout=10)
                if response.status_code == 200:
                    print("Ping sent successfully")
                else:
                    print(f"Ping failed with status code: {response.status_code}")
        except requests.exceptions.Timeout:
            print("Ping timeout")
        except Exception as e:
            print(f"Ping failed: {str(e)}")
        time_module.sleep(30)  # 30秒ごとにping

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
    return """あなたはタスク管理アシスタントです。ユーザーのメッセージを解析し、適切なアクションを判断してください。

アクションの種類：
1. register: タスクの登録
2. complete: タスクの完了
3. list: タスク一覧の表示
4. list_date: 特定の日付のタスク一覧
5. remind: リマインドの設定
6. current_time: 現在の日時を確認

応答は以下のJSON形式で返してください：
{
    "action": "register" | "complete" | "list" | "list_date" | "remind" | "current_time",
    "task_content": "タスクの内容",
    "date": "日付（YYYY-MM-DD形式）",
    "time": "時間（HH:MM形式）",
    "remind_time": "リマインド時間（HH:MM形式）"
}
"""

def process_message_with_llm(message: str) -> Dict[str, Any]:
    """LLMを使用してメッセージを処理し、アクションを判断する"""
    try:
        print(f"process_message_with_llm: 入力メッセージ = {message}")
        
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
        print(f"process_message_with_llm: LLM応答 = {result}")
        
        # 日付の解析を改善
        if result.get('date'):
            print(f"process_message_with_llm: 日付の解析前 = {result['date']}")
            # 今日の予定を要求している場合は日付を空にする
            if result['date'].lower() in ['今日', 'きょう', 'today']:
                result['date'] = None
            else:
                parsed_date = parse_date(result['date'])
                result['date'] = parsed_date.strftime('%Y-%m-%d')
            print(f"process_message_with_llm: 日付の解析後 = {result['date']}")
        
        return result
    except Exception as e:
        print(f"Error processing message with LLM: {str(e)}")
        return None

def handle_task_registration(user_id: str, task_content: str, date: str, time: str, remind_time: str = None) -> str:
    """タスクを登録する"""
    try:
        # 現在の日時を取得
        current_datetime = get_current_jst_datetime()
        print(f"現在の日時: {current_datetime}")
        
        # 日付のバリデーション
        task_date = parse_date(date)
        print(f"タスクの日付: {task_date}")
        print(f"タスクの日付（日付部分）: {task_date.date()}")
        print(f"現在の日付（日付部分）: {current_datetime.date()}")
        
        # 日付の比較（日付部分のみ）
        if task_date.date() < current_datetime.date():
            print(f"日付比較: {task_date.date()} < {current_datetime.date()}")
            return f'過去の日付にはタスクを登録できません。今日以降の日付を指定してください。'
        
        # 時間のバリデーション
        if time:
            try:
                # 時間をdatetimeオブジェクトに変換
                task_time = datetime.strptime(time, '%H:%M').time()
                task_datetime = task_date.replace(hour=task_time.hour, minute=task_time.minute)
                print(f"タスクの日時: {task_datetime}")
                
                # 同じ日付の場合のみ時間を比較
                if task_date.date() == current_datetime.date():
                    if task_datetime < current_datetime:
                        print(f"時間比較: {task_datetime} < {current_datetime}")
                        return f'過去の時間にはタスクを登録できません。現在時刻以降の時間を指定してください。'
            except ValueError:
                return f'時間の形式が正しくありません。HH:MM形式で指定してください。'
        
        # タスクを登録
        data = {
            'user_id': user_id,
            'content': task_content,
            'date': task_date.strftime('%Y-%m-%d'),
            'time': time,
            'remind_time': remind_time,
            'created_at': format_jst_datetime(current_datetime)
        }
        
        supabase.table('tasks').insert(data).execute()
        
        # 登録完了メッセージを生成
        date_str = task_date.strftime('%Y年%m月%d日')
        time_str = f' {time}' if time else ''
        return f'タスクを登録しました:\n{date_str}{time_str} {task_content}'
    except Exception as e:
        print(f"エラー: {str(e)}")
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
        current_datetime = get_current_jst_datetime()
        print(f"handle_task_list: 現在の日時 = {current_datetime}")
        print(f"handle_task_list: 日付部分 = {current_datetime.date()}")
        
        # 日付の処理
        if date:
            print(f"handle_task_list: 指定された日付 = {date}")
            # 日付文字列をdatetimeオブジェクトに変換
            task_date = parse_date(date)
            print(f"handle_task_list: 解析された日付 = {task_date}")
            query_date = task_date.strftime('%Y-%m-%d')
        else:
            print(f"handle_task_list: 今日の日付を使用 = {current_datetime.date().isoformat()}")
            query_date = current_datetime.date().isoformat()
            task_date = current_datetime
        
        # タスクの取得
        query = supabase.table('tasks').select('*').eq('user_id', user_id).eq('scheduled_date', query_date)
        response = query.order('scheduled_time').execute()
        tasks = response.data
        print(f"handle_task_list: 取得したタスク数 = {len(tasks)}")
        
        if not tasks:
            date_str = '今日' if task_date.date() == current_datetime.date() else task_date.strftime('%m/%d')
            return f'{date_str}のタスクはありません'
        
        # タスク一覧の作成
        date_str = '今日' if task_date.date() == current_datetime.date() else task_date.strftime('%m/%d')
        task_list = [f'【{date_str}のタスク】']
        for task in tasks:
            status = '✅' if task['is_done'] else '⏳'
            time_str = f"{task['scheduled_time']} " if task['scheduled_time'] else ''
            task_list.append(f"{status} {time_str}{task['content']}")
        
        return '\n'.join(task_list)
    except Exception as e:
        print(f"handle_task_list: エラー発生 = {str(e)}")
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

def handle_current_time() -> str:
    """現在の日時を返す"""
    current_datetime = get_current_jst_datetime()
    print(f"handle_current_time: 現在の日時 = {current_datetime}")
    print(f"handle_current_time: 日付部分 = {current_datetime.date()}")
    return f'現在の日時は {current_datetime.strftime("%Y年%m月%d日 %H時%M分")} です。'

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
    
    # メッセージが空の場合は処理をスキップ
    if not message.strip():
        return

    # LLMでメッセージを処理
    result = process_message_with_llm(message)
    if not result:
        return

    # アクションに応じて処理
    try:
        response_text = ""
        action = result['action']
        if action == 'register':
            if not result.get('task_content'):
                raise ValueError("タスクの内容が指定されていません")
            response_text = handle_task_registration(user_id, result['task_content'], result['date'], result['time'], result.get('remind_time'))
        elif action == 'complete':
            if not result.get('task_content'):
                raise ValueError("完了するタスクが指定されていません")
            response_text = handle_task_completion(user_id, result['task_content'])
        elif action == 'list':
            response_text = handle_task_list(user_id)
        elif action == 'list_date':
            response_text = handle_task_list(user_id, result['date'])
        elif action == 'remind':
            response_text = handle_reminder(user_id, result['date'], result['time'])
        elif action == 'current_time':
            response_text = handle_current_time()
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