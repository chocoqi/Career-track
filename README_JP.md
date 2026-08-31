English: [README.md](README.md)

# Career Compass

学生・若手人材の求人探索と市場動向の把握を支援する、Streamlit ベースのキャリアトラッキング・プロトタイプです。

> **開発状況:** 本プロジェクトは、コンセプトと実装方針を示すためのデモ／プロトタイプであり、完成済み・本番運用可能な製品ではありません。実際の運用に向けては、一部機能、エッジケース、操作性、技術的課題について、追加の開発と検証が必要です。

## 概要

Career Compass は、複数の求人フィードから取得した情報を共通形式に整え、1つの画面で検索・絞り込みできる Web アプリケーションです。学位、専攻、検索キーワードをプロフィールとして保存し、取得した求人のスナップショットを日次で蓄積することで、このアプリが観測した求人の増減を可視化します。

求人への応募は各提供元のページで行います。本アプリが表示する件数は接続済みフィードの観測結果であり、各国の求人市場全体を表すものではありません。

## 背景・課題

求人情報は複数のサービスに分散しており、提供元によって項目や表記も異なります。また、学生にとっては「現在どのような求人があるか」だけでなく、学位との適合性や求人の出入りを継続的に把握することも容易ではありません。

本プロジェクトでは、複数フィードのデータを同じ形式に正規化し、プロフィールに基づく検索、フィルタリング、日次スナップショットの比較を1つのアプリにまとめています。

## 主な機能

- ローカルアカウントの作成・ログイン、1回限りの復旧コードによるパスワード再設定、14日間のセッション、アカウントのリンク・切り替え、ログアウト、削除
- 学位・分野・専門・検索キーワード・任意の性別情報を含むトラッキングプロフィール
- Arbeitnow、Remotive、および設定済みの Adzuna、Greenhouse、Lever、USAJOBS からの求人取得
- 提供元ごとに異なる求人データの共通スキーマへの正規化と重複排除
- 国、提供元、雇用形態、勤務形態、掲載日、掲載状態、学位適合性による絞り込み
- USAJOBS 公開アーカイブを利用した、終了済み米国連邦政府求人の検索
- ユーザー・検索条件単位の日次スナップショット、新規・消失求人と観測件数の可視化、元データの確認、CSV 出力
- Twilio 設定時の SMS 求人通知、配信停止、定期実行用ワーカー
- 固定ルールに基づくスキル候補と公的キャリア情報へのリンク提示
- 日本・シンガポール向け外部求人サイトへのリンク

## システム構成

本リポジトリには独立した REST API や React フロントエンドはありません。Streamlit が Python コードから UI と Web サーバーを提供し、アプリ内の関数を直接呼び出します。

```text
ユーザー（ブラウザ）
        ↓
Streamlit UI / session state（streamlit_app.py）
        ↓                         ↓
認証・データ処理                  求人提供元 API
（auth.py / career_data.py）      Arbeitnow / Remotive / Adzuna /
        ↓                         Greenhouse / Lever / USAJOBS
SQLite（career_tracker.db）       ↓
        └──── pandas DataFrame に正規化 ────┘
                          ↓
                  表・グラフとして表示

daily_digest.py → 求人取得・差分確認 → Twilio → SMS
```

## 使用技術

| 技術 | 用途 |
|---|---|
| Python 3 | UI、データ処理、認証、定期ワーカーの実装 |
| Streamlit 1.62 | Web UI、フォーム、session state、キャッシュ、表、CSV ダウンロード |
| JavaScript | カスタム Streamlit component からブラウザの `localStorage` にセッショントークンを保存 |
| pandas | 求人データの正規化、絞り込み、集計、CSV 生成 |
| Altair | 求人動向の複数系列グラフ |
| SQLite | アカウント、プロフィール、購読、スナップショット、配信済み求人の保存 |
| Requests | 求人提供元 API への HTTPS GET リクエスト |
| Twilio SDK | 日次 SMS 通知の送信 |
| GitHub Actions | `daily_digest.py` の日次実行設定 |

## 工夫した点

- 提供元ごとに異なる JSON を、求人 ID、職種、企業、国、雇用形態、掲載日などの共通スキーマへ変換しています。
- URL・タイトル・企業名などから安定したハッシュ ID を生成し、同一求人の重複を抑えています。
- 求人 ID の日次集合を比較し、「新規」「消失」「観測中」の件数を算出しています。ユーザーと検索クエリ単位でスナップショットを分離しています。
- 1つの提供元でエラーが起きても、他の提供元の取得を継続し、UI に取得失敗の詳細を表示します。
- パスワードと復旧コードは PBKDF2-HMAC-SHA256 と個別 salt でハッシュ化し、ブラウザ用セッショントークンも SQLite にはハッシュのみを保存します。
- SMS は送信成功後に求人を配信済みとして記録し、同じ求人を翌日「新着」として再送しにくい構成です。

## セキュリティとデータ管理

パスワードと復旧コードは、個別の salt を用いた PBKDF2-HMAC-SHA256 でハッシュ化しています。ブラウザに保持するランダムなセッショントークンも、SQLite には SHA-256 ハッシュと有効期限のみを保存します。

一方、プロフィール、任意の性別情報、電話番号はローカル SQLite に通常のデータとして保存されます。公開サービス化する場合は、managed identity、ホスト型 DB、ユーザー単位のアクセス制御、HTTPS、監査ログなどの追加対策が必要です。

## 実行方法

```powershell
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

Arbeitnow と Remotive は追加設定なしで利用できます。その他の求人ソースは必要に応じて環境変数を設定します。

```powershell
$env:ADZUNA_APP_ID="your-app-id"
$env:ADZUNA_APP_KEY="your-app-key"
$env:GREENHOUSE_BOARDS="company-one,company-two"
$env:LEVER_SITES="company-one,company-two"
$env:USAJOBS_API_KEY="your-api-key"
$env:USAJOBS_EMAIL="your-email"
streamlit run streamlit_app.py
```

Greenhouse には `boards.greenhouse.io/<token>` の token、Lever には `jobs.lever.co/<site>` の site 名を設定します。複数指定する場合はカンマで区切ります。

SMS ワーカーを実行する場合は、アプリで購読を保存したうえで Twilio の環境変数を設定します。

```powershell
$env:TWILIO_ACCOUNT_SID="your-account-sid"
$env:TWILIO_AUTH_TOKEN="your-auth-token"
$env:TWILIO_FROM_NUMBER="your-twilio-number"
python daily_digest.py
```

ポートはリポジトリ内で固定されていません。起動時に Streamlit がターミナルへ表示する URL を使用してください。GitHub Actions の定期ワークフローは 00:15 UTC に設定され、手動実行にも対応しています。Streamlit が UI と Python のアプリケーション処理をまとめて提供するため、フロントエンドとバックエンドを別々に起動する必要はありません。

## 現在の制限

- 取得件数は接続済みフィードの範囲に限られ、求人市場全体を表しません。特に国・地域によって網羅性が異なります。
- 国、雇用形態、学位要件、掲載状態の一部は単純な文字列ルールによる推定であり、誤分類の可能性があります。
- 長期グラフは実際に保存したスナップショットのみを表示します。過去5年分のデータを自動生成するものではありません。
- Career coach は LLM や生成 AI ではなく、キーワードに応じて固定のスキル候補を返すルールベース機能です。
- API の timeout とエラー分離はありますが、retry、exponential backoff、rate limit 対応、構造化ログは未実装です。
- SQLite はローカル利用向けです。GitHub-hosted runner には DB が永続化されないため、現状の GitHub Actions だけでは購読・履歴を安定運用できません。
- SMS の STOP 応答処理、各国の送信規制対応、運用上の同意管理は未完成です。
- 自動テストは見当たりません。

## 今後の改善点

- 求人データの正規化、認証、スナップショット差分、フィルタ、SMS の重複防止に対する自動テストを追加する。現状のリポジトリにはテストスイートがありません。
- 公開運用前にデータをホスト型 DB へ移行し、managed identity、ユーザー単位のアクセス制御、HTTPS、rate limiting、監査ログを整備する。
- API の retry、backoff、rate limit 対応、構造化ログを追加する。現状は timeout と提供元別のエラー表示はありますが、再試行処理はありません。
- 横幅の大きい求人テーブル、フィルタ用 popover、グラフ、フォーム、ナビゲーションについて、モバイル画面、キーボード操作、支援技術、複数ブラウザで検証し、必要に応じて調整する。リポジトリ内にはこれらの検証結果がありません。
- 通知頻度などの設定を明確にし、SMS の受信側での STOP／返信処理を完成させる。現状は1アカウントにつき有効な検索条件を1件保存でき、アプリ内の配信停止ボタンを利用できます。

## 開発形態

個人プロジェクトとして、求人データの取得・正規化、Streamlit UI、ローカル認証、SQLite による永続化、求人動向の可視化、SMS 通知ワーカーを1つのリポジトリに実装しています。
