---
name: eval-loop
description: 制作物（音楽・小説・画像 など）を評価し、捨てた「理由」から学んで次の一手を決める汎用ループ。ドメイン側は manifest と CURATION（status/reason）を用意するだけ。collect→featurize→learn(bqmlite)→interpret を回す。MX の measure→learn→update に相当。「評価ループ」「eval-loop」「なぜ捨てた」「捨てた理由」「当たり外れを学ぶ」「bqmliteで評価」「コンテンツ評価」「裁く」などのキーワードで発動。
---

# eval-loop — 制作物の評価ループ（汎用）

**作る（gen）と裁く（eval）を分ける。** 音楽・小説・画像…同じ型で回す。
ドメイン側は **manifest** と **CURATION** を用意するだけ（実装を持たない）。

## 契約（ドメイン側が用意する）

```
<root>/<project>/manifest.json    項目（items / tracks / chapters / episodes …）
<root>/CURATION.json              { "items": { "<id>": { "status": "discard", "reason": "…" } } }
```

- `status`: deploy / adopt / undecided / hide / discard（意味はドメインが決めてよい）
- `reason`: 捨てた理由（**なぜだめなのか**）※これが学習と改善の核
- `id`: 項目を一意に（音楽なら spec、小説なら章番号 等）

## ループ

```
collect   項目と CURATION を集める（重複は1回）
featurize 数値特徴を作る（item の数値 + title長 / cover有無 / 長さ …）
learn     bqmlite（Go）で discard を学習（logistic_regression）
interpret 捨てた理由を読み、次に捨てられそうな上位を出す
```

## 使い方

```bash
S=~/repo/MX/eval-loop/scripts/eval_loop.py

python3 "$S" --root ~/repo/suno-gen/albums          # 音楽
python3 "$S" --root ~/novels --engine logistic_regression   # 小説
python3 "$S" --root ~/images                        # 画像
python3 "$S" --root ./content --report-only         # ML 抜きで理由だけ
```

- 出力: `<root>/../eval/eval-dataset.json`・`eval-items.json`・`eval-model-result.json`
- bqmlite-go（`~/repo/bqmlite-go` か `$BQMLITE`）が必要。無ければ理由レポートだけ。

## MX サイクルとの関係

| MX | eval-loop |
|---|---|
| measure | collect / featurize |
| learn | bqmlite + 理由の解釈 |
| update | 次に捨てられそう上位 → 次の制作判断 |

## 設計原則

- **method はここ（MX）／data は各ドメイン**（疎結合）。manifest JSON が契約。
- **操作（status/reason を付ける）はドメインの UI/TUI**（eval-loop は読むだけ）。
- **理由（reason）を必ず書く**。数字だけでなく「なぜ」が次の学習になる。
- 標準ライブラリのみ（bqmlite は Go を spawn）。
