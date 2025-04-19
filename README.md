# LINEタスク管理Bot

LINEから簡単なコマンドで時間付きタスクを管理できるBotです。

## 機能

- タスクの登録（時間指定可）
- タスクの完了
- タスク一覧の確認
- 自動通知（朝8時・昼12時）

## 使用方法

### タスク登録
```
タスク 15:00 プレゼン資料作成
タスク 散歩
```

### タスク完了
```
完了 プレゼン資料作成
```

### タスク一覧確認
```
リスト
今日のタスク
```

## セットアップ

1. 必要なパッケージのインストール
```bash
pip install -r requirements.txt
```

2. 環境変数の設定
`.env`ファイルに以下の情報を設定：
```
LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token
LINE_CHANNEL_SECRET=your_channel_secret
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
```

3. Supabaseの設定
- `tasks`テーブルを作成
- 以下のカラムを設定：
  - id (UUID, 主キー)
  - user_id (TEXT)
  - content (TEXT)
  - is_done (BOOLEAN)
  - created_at (TIMESTAMP)
  - scheduled_date (DATE)
  - scheduled_time (TIME, nullable)

4. アプリケーションの起動
```bash
python main.py
```

5. 通知スクリプトの実行
```bash
python notify.py
```

## 注意事項

- 通知スクリプトは定期的に実行する必要があります（cron等で設定）
- LINE Messaging APIの設定が必要です
- Supabaseのプロジェクト設定が必要です 