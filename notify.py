import os
from dotenv import load_dotenv
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi
from linebot.v3.messaging import TextMessage
from supabase import create_client, Client
from datetime import datetime, time
import pytz

# 環境変数の読み込み
load_dotenv()

# LINE Botの設定
configuration = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
client = ApiClient(configuration)
line_bot_api = MessagingApi(client)

# Supabaseの設定
supabase: Client = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_KEY')
)

def send_morning_notification():
    """朝8時のタスク一覧通知"""
    jst = pytz.timezone('Asia/Tokyo')
    today = datetime.now(jst).date()
    
    # 全ユーザーのタスクを取得
    response = supabase.table('tasks').select('*').eq('scheduled_date', today).order('scheduled_time').execute()
    tasks = response.data
    
    # ユーザーごとにタスクをグループ化
    user_tasks = {}
    for task in tasks:
        if task['user_id'] not in user_tasks:
            user_tasks[task['user_id']] = []
        user_tasks[task['user_id']].append(task)
    
    # 各ユーザーに通知を送信
    for user_id, user_task_list in user_tasks.items():
        if not user_task_list:
            continue
            
        message = [f'【今日のタスク（{today.strftime("%m/%d")}）】']
        for task in user_task_list:
            time_str = f"{task['scheduled_time']} " if task['scheduled_time'] else ''
            status = '✅' if task['is_done'] else '⏳'
            message.append(f"{status} {time_str}{task['content']}")
        
        try:
            line_bot_api.push_message_with_http_info({
                'to': user_id,
                'messages': [TextMessage(text='\n'.join(message))]
            })
        except Exception as e:
            print(f"Error sending notification to {user_id}: {e}")

def send_afternoon_notification():
    """昼12時の未完了タスク通知"""
    jst = pytz.timezone('Asia/Tokyo')
    today = datetime.now(jst).date()
    
    # 未完了のタスクを取得
    response = supabase.table('tasks').select('*').eq('scheduled_date', today).eq('is_done', False).order('scheduled_time').execute()
    tasks = response.data
    
    # ユーザーごとにタスクをグループ化
    user_tasks = {}
    for task in tasks:
        if task['user_id'] not in user_tasks:
            user_tasks[task['user_id']] = []
        user_tasks[task['user_id']].append(task)
    
    # 各ユーザーに通知を送信
    for user_id, user_task_list in user_tasks.items():
        if not user_task_list:
            continue
            
        message = ['【未完了タスクの進捗確認】']
        for task in user_task_list:
            time_str = f"{task['scheduled_time']} " if task['scheduled_time'] else ''
            message.append(f"⏳ {time_str}{task['content']}")
        
        try:
            line_bot_api.push_message_with_http_info({
                'to': user_id,
                'messages': [TextMessage(text='\n'.join(message))]
            })
        except Exception as e:
            print(f"Error sending notification to {user_id}: {e}")

if __name__ == "__main__":
    # 現在の時刻を取得
    jst = pytz.timezone('Asia/Tokyo')
    current_time = datetime.now(jst).time()
    
    # 朝8時の通知
    if current_time.hour == 8 and current_time.minute == 0:
        send_morning_notification()
    
    # 昼12時の通知
    elif current_time.hour == 12 and current_time.minute == 0:
        send_afternoon_notification() 