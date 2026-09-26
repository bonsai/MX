#!/usr/bin/env python3
"""
eval_loop.py — 制作物の評価ループ（汎用）。音楽 / 小説 / 画像 … 同じ型で回す。

流れ: collect（集める）→ featurize（特徴量化）→ learn（bqmlite で学習）→ interpret（解釈）

入力（ドメイン側が用意する契約）:
    <root>/<project>/manifest.json   項目（items/tracks/chapters/…）
    <root>/CURATION.json             { items: { "<id>": {status, reason, ...} } }

使い方:
    python3 eval_loop.py --root ~/repo/suno-gen/albums
    python3 eval_loop.py --root ./content --engine logistic_regression
    python3 eval_loop.py --root ./content --report-only     # ML 抜きで理由だけ

bqmlite（Go）を呼ぶ。無ければ理由レポートだけ出す。
標準ライブラリのみ。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DISCARD = {"discard", "reject", "dropped", "❌"}
KEEP = {"adopt", "deploy", "kept", "published", "⭐", "✅", "🚀"}


def jload(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def items_of(m: dict) -> list[dict]:
    for k in ("items", "tracks", "chapters", "episodes", "entries"):
        if isinstance(m.get(k), list):
            return m[k]
    return []


def collect(root: Path) -> tuple[list[dict], dict]:
    rows, curation = [], {}
    cur = jload(root / "CURATION.json", {})
    cur = cur.get("items", cur) if isinstance(cur, dict) else {}
    seen: set = set()
    for mp in sorted(root.glob("*/manifest.json")):
        m = jload(mp, {})
        project = m.get("album") or m.get("project") or m.get("title") or mp.parent.name
        for it in items_of(m):
            iid = it.get("spec") or it.get("id") or it.get("slug") or it.get("title")
            if iid in seen:      # 同じ曲が複数アルバムに出ても1回
                continue
            seen.add(iid)
            c = cur.get(iid, {}) if isinstance(cur, dict) else {}
            rows.append({
                "id": iid, "project": project,
                "status": c.get("status", it.get("status", "")),
                "reason": c.get("reason", ""),
                "item": it, "manifest": m,
            })
    return rows, cur


def featurize(row: dict) -> dict:
    """ドメイン非依存の最小特徴量。item に数値があれば拾い、無ければ導出する。"""
    it, m = row["item"], row["manifest"]
    f = {}
    # 数値フィールドを拾う
    for k, v in it.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            f[k] = v
    # 導出
    f["title_len"] = len(str(it.get("title") or row["id"] or ""))
    f["has_cover"] = 1 if (it.get("cover") or m.get("cover")) else 0
    f["clips"] = int(it.get("clips") or 0)
    f["instrumental"] = 1 if it.get("instrumental") else 0
    f["parts"] = len(it.get("parts") or [])
    f.setdefault("track_count", int(m.get("track_count") or 0))
    f["discard"] = 1 if str(row["status"]).lower() in DISCARD else 0
    return f


def find_bqmlite() -> Path | None:
    for c in (os.environ.get("BQMLITE"), str(Path.home() / "repo/bqmlite-go"),
              str(Path.home() / "bqmlite-go")):
        if c and (Path(c) / "cmd" / "bqmlite").exists():
            return Path(c)
    return None


def run_bqmlite(bq: Path, dataset: Path, engine: str, out: Path) -> dict | None:
    if not shutil.which("go"):
        return None
    try:
        subprocess.run(["go", "run", "./cmd/bqmlite", "-input", str(dataset),
                        "-engine", engine, "-output", str(out)],
                       cwd=str(bq), check=True)
        return jload(out, None)
    except Exception as e:  # noqa: BLE001
        print(f"  bqmlite 失敗: {e}", file=sys.stderr)
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="制作物の評価ループ（汎用）")
    ap.add_argument("--root", required=True, help="content root（*/manifest.json を持つ）")
    ap.add_argument("--engine", default="logistic_regression")
    ap.add_argument("--out", default="", help="出力先（既定 <root>/../eval）")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    if not root.exists():
        sys.exit(f"root が無い: {root}")
    out = Path(args.out).expanduser() if args.out else (root.parent / "eval")
    out.mkdir(parents=True, exist_ok=True)

    rows, curation = collect(root)
    if not rows:
        sys.exit("manifest に項目が無い（items/tracks/chapters を確認）")

    # dataset（bqmlite は数値のみ）
    ds_rows = []
    idmap = []
    for r in rows:
        f = featurize(r)
        ds_rows.append(f)
        idmap.append({"id": r["id"], "project": r["project"],
                      "status": r["status"], "reason": r["reason"]})
    dataset = {"name": "eval-loop", "target": "discard", "rows": ds_rows}
    ds_path = out / "eval-dataset.json"
    ds_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    (out / "eval-items.json").write_text(
        json.dumps(idmap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    disc = [r for r in idmap if str(r["status"]).lower() in DISCARD]
    print(f"[1/3] collect: {len(rows)} 項目 / discard {len(disc)} / プロジェクト "
          f"{len({r['project'] for r in rows})}")
    print(f"      dataset -> {ds_path}")

    print(f"[2/3] learn   : bqmlite ({args.engine})")
    res = None
    if not args.report_only:
        bq = find_bqmlite()
        if bq:
            res = run_bqmlite(bq, ds_path, args.engine, out / "eval-model-result.json")
            print(f"      model -> {out/'eval-model-result.json'}"
                  if res else "      （結果なし）")
        else:
            print("      bqmlite-go が見つからない（--report-only 相当）")

    print("[3/3] interpret: 捨てた理由（なぜだめなのか）")
    if not disc:
        print("  （discard に理由がまだ無い）")
    for r in disc:
        print(f"  - [{r['project']}] {r['id']}: {r['reason'] or '(理由未記入)'}")
    if res:
        probs = [x.get("probability", 0) for x in res.get("results", [])]
        if probs:
            top = sorted(range(len(probs)), key=lambda i: -probs[i])[:5]
            print("\n  次に捨てられそう（discard 確率 上位）:")
            for i in top:
                if probs[i] > 0:
                    print(f"    {probs[i]:.3f}  {idmap[i]['id']}")


if __name__ == "__main__":
    main()
