/**
 * reviser — 生成プロンプトの改訂者（LLM エージェント）。
 *
 * 入力: 評価の重み（prompt-weights.json）と捨てた理由（reason）。
 * 出力: プロンプト/parts の差分提案（JSON）。**適用はしない**（人が承認）。
 */
import { Agent } from '@mastra/core/agent';
import { google } from '@ai-sdk/google';

const MODEL = process.env.REVISER_MODEL ?? 'gemini-2.5-flash';

export const reviser = new Agent({
  id: 'prompt-reviser',
  name: 'prompt-reviser',
  instructions: `あなたは生成プロンプトの改訂者です。評価データから、次の生成バッチの
プロンプト（parts / style / 言語戦略）をどう変えるかを提案します。

原則:
- 重み(weight)が正で件数(n)が十分なファセットは増やす。負は減らす/避ける。
- 捨てた理由(reason)を必ず読む。数字だけでなく「なぜ」に応える。
- 提案は必ず JSON で返す。スキーマ:
  {"add":[{"facet":"", "why":""}], "remove":[{"facet":"", "why":""}],
   "rewrite":[{"target":"style|lyrics|parts", "from":"", "to":"", "why":""}],
   "route":"路線変更の一文", "confidence":0.0}
- 破壊的な一括変更はしない。小さく試せる差分にする。
- 確認できないことは断定しない。`,
  model: google(MODEL),
});
