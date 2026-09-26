#!/usr/bin/env python3
"""
prompt_weights.py — 評価データから「生成プロンプトの重み」を出し、路線変更を提案する（汎用）。

評価（CURATION の status/reason）を、生成入力の**ファセット**（parts / tags / パラメータ）に
結びつけ、**どのファセットが当たりに効くか**を重みで示す。重みは透明・決定論的に計算
（LLM 不要）。理由（reason）は解釈の材料として並べる。

使い方:
    python3 prompt_weights.py --root ~/repo/suno-gen/albums
    python3 prompt_weights.py --root ./content --facet parts     # facets の出所
    python3 prompt_weights.py --root ./content --facet tags

契約:
    <root>/*/manifest.json（項目。items[].parts か items[].tags を持つ）
    <root>/CURATION.json  { items: { "<id>": {status, reason} } }

重み:
    keep = 1（adopt/deploy）, discard = 0。undecided/hide/未設定は学習から除外。
    w(f) = mean(keep | f あり) − mean(keep | f なし)     （−1..+1）
    支持度 support = 件数。件数が少ないファセットは信頼しない（min_count）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

KEEP = {"adopt", "deploy", "kept", "published", "⭐", "✅", "🚀"}
DISCARD = {"discard", "reject", "dropped", "❌"}


def jload(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def collect(root: Path, facet: str) -> tuple[list[dict], dict]:
    cur = jload(root / "CURATION.json", {})
    cur = cur.get("items", cur) if isinstance(cur, dict) else {}
    out, seen = [], set()
    for mp in sorted(root.glob("*/manifest.json")):
        m = jload(mp, {})
        items = next((m[k] for k in ("items", "tracks", "chapters", "episodes", "entries")
                      if isinstance(m.get(k), list)), [])
        for it in items:
            iid = it.get("spec") or it.get("id") or it.get("slug") or it.get("title")
            if iid in seen:
                continue
            seen.add(iid)
            c = cur.get(iid, {}) if isinstance(cur, dict) else {}
            facets = [str(x) for x in (it.get(facet) or [])]
            out.append({"id": iid, "facets": facets,
                        "status": c.get("status", it.get("status", "")),
                        "reason": c.get("reason", "")})
    return out, cur


def outcome(status: str) -> int | None:
    s = str(status).lower()
    if s in KEEP:
        return 1
    if s in DISCARD:
        return 0
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="評価→プロンプト重み（汎用）")
    ap.add_argument("--root", required=True)
    ap.add_argument("--facet", default="parts", help="ファセットの出所（parts / tags …）")
    ap.add_argument("--min-count", type=int, default=3, help="この件数未満は信頼しない")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    if not root.exists():
        sys.exit(f"root が無い: {root}")
    out = Path(args.out).expanduser() if args.out else (root.parent / "eval")
    out.mkdir(parents=True, exist_ok=True)

    rows, _ = collect(root, args.facet)
    labelled = [(r, outcome(r["status"])) for r in rows]
    labelled = [(r, y) for r, y in labelled if y is not None]
    if not labelled:
        sys.exit("keep/discard のラベルが無い（CURATION で adopt/discard を付ける）")

    base = sum(y for _, y in labelled) / len(labelled)   # 全体の当たり率
    # ファセットごとの重み
    with_f: dict[str, list[int]] = defaultdict(list)
    without_f: dict[str, list[int]] = defaultdict(list)
    allf = set()
    for r, y in labelled:
        for f in r["facets"]:
            allf.add(f)
    for f in allf:
        for r, y in labelled:
            (with_f[f] if f in r["facets"] else without_f[f]).append(y)

    stats = []
    for f in allf:
        w, wo = with_f[f], without_f[f]
        n = len(w)
        mw = sum(w) / n if n else 0
        mo = sum(wo) / len(wo) if wo else base
        stats.append({"facet": f, "n": n, "keep_rate": round(mw, 3),
                      "weight": round(mw - mo, 3),
                      "discards": sum(1 for r, y in labelled if y == 0 and f in r["facets"])})
    stats.sort(key=lambda s: -s["weight"])

    print(f"# プロンプト重み（facet={args.facet}）")
    print(f"  ラベル付き {len(labelled)} 項目 / 当たり率 {base:.2f} / min_count={args.min_count}")
    print()
    print("  FAVOR（当たりに効く）")
    for s in [x for x in stats if x["weight"] > 0 and x["n"] >= args.min_count][:12]:
        print(f"    +{s['weight']:.2f}  n={s['n']:<3} keep率={s['keep_rate']:.2f}  {s['facet']}")
    print("  AVOID（外れに効く）")
    for s in [x for x in stats if x["weight"] < 0 and x["n"] >= args.min_count][::-1][:12]:
        print(f"    {s['weight']:.2f}  n={s['n']:<3} keep率={s['keep_rate']:.2f}  {s['facet']}")
    print("  （件数が少ない＝信頼薄）")
    for s in stats:
        if s["n"] < args.min_count:
            print(f"    n={s['n']}  {s['facet']}")

    (out / "prompt-weights.json").write_text(
        json.dumps({"facet": args.facet, "base_keep_rate": round(base, 3),
                    "weights": stats}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"\n  wrote {out/'prompt-weights.json'}")

    # 路線変更の提案
    print("\n# 路線変更の提案（自動・たたき台）")
    favors = [s["facet"] for s in stats if s["weight"] > 0.1 and s["n"] >= args.min_count]
    avoids = [s["facet"] for s in stats if s["weight"] < -0.1 and s["n"] >= args.min_count]
    if favors:
        print(f"  - 増やす: {', '.join(favors)}")
    if avoids:
        print(f"  - 減らす/避ける: {', '.join(avoids)}")
    print("  - 理由（reason）を見て、言語・声・構成のどこを直すか決める")


if __name__ == "__main__":
    main()
