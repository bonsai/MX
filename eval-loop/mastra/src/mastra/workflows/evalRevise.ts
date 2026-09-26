/**
 * evalRevise — 評価 → プロンプト改訂 のワークフロー（Mastra / TS）。
 *
 *   collect（重みと理由を集める） → revise（エージェントが差分提案） → propose（書き出す）
 *
 * **適用はしない**。提案を JSON に出し、人が承認してからドメイン側で反映する（承認ゲート）。
 */
import { createWorkflow, createStep } from '@mastra/core/workflows';
import { z } from 'zod';
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { reviser } from '../agents/reviser.ts';

const EvalInput = z.object({
  root: z.string(),                       // content root（*/manifest.json）
  facet: z.string().default('parts'),
  out: z.string().optional(),             // 出力先
  script: z.string().optional(),          // prompt_weights.py のパス
});

const Weights = z.object({
  facet: z.string(),
  base_keep_rate: z.number(),
  weights: z.array(z.object({
    facet: z.string(), n: z.number(), keep_rate: z.number(), weight: z.number(),
  })),
});

const CollectOut = z.object({
  root: z.string(), facet: z.string(), out: z.string(),
  weights: Weights,
  reasons: z.array(z.object({ id: z.string(), status: z.string(), reason: z.string() })),
});

const collectStep = createStep({
  id: 'collect',
  inputSchema: EvalInput,
  outputSchema: CollectOut,
  execute: async ({ inputData }) => {
    const { root } = inputData;
    const out = inputData.out || join(root, '..', 'eval');
    const script = inputData.script
      || join(import.meta.dir, '..', '..', '..', 'scripts', 'prompt_weights.py');
    // 重みは既存の決定論エンジンで計算（LLM 不要）
    if (existsSync(script)) {
      Bun.spawnSync(['python3', script, '--root', root, '--facet', inputData.facet,
                     '--min-count', '2', '--out', out], { stdout: 'ignore', stderr: 'ignore' });
    }
    const wf = join(out, 'prompt-weights.json');
    const weights = existsSync(wf)
      ? JSON.parse(readFileSync(wf, 'utf8'))
      : { facet: inputData.facet, base_keep_rate: 0, weights: [] };
    // 捨てた理由
    const cf = join(out, 'eval-items.json');
    let reasons: { id: string; status: string; reason: string }[] = [];
    if (existsSync(cf)) {
      reasons = (JSON.parse(readFileSync(cf, 'utf8')) as any[])
        .filter((r) => String(r.status).toLowerCase().includes('discard') || r.reason)
        .map((r) => ({ id: r.id, status: r.status ?? '', reason: r.reason ?? '' }));
    }
    return { root, facet: inputData.facet, out, weights, reasons };
  },
});

const ReviseOut = z.object({
  root: z.string(), out: z.string(),
  proposal: z.any(),
});

const reviseStep = createStep({
  id: 'revise',
  inputSchema: CollectOut,
  outputSchema: ReviseOut,
  execute: async ({ inputData }) => {
    const prompt = [
      '## 評価の重み（facet別）',
      JSON.stringify(inputData.weights, null, 2),
      '',
      '## 捨てた理由（なぜだめなのか）',
      inputData.reasons.map((r) => `- ${r.id}: ${r.reason || '(理由未記入)'}`).join('\n'),
      '',
      '上を踏まえ、次の生成バッチのプロンプト改訂を JSON で提案してください。',
    ].join('\n');
    let proposal: any;
    try {
      const res = await reviser.generate(prompt);
      const text = typeof res.text === 'string' ? res.text : JSON.stringify(res);
      const m = text.match(/\{[\s\S]*\}/);
      proposal = m ? JSON.parse(m[0]) : { raw: text };
    } catch (e: any) {
      proposal = { error: String(e?.message ?? e),
                   fallback: { add: inputData.weights.weights.filter((w: any) => w.weight > 0.1),
                               remove: inputData.weights.weights.filter((w: any) => w.weight < -0.1) } };
    }
    return { root: inputData.root, out: inputData.out, proposal };
  },
});

const proposeStep = createStep({
  id: 'propose',
  inputSchema: ReviseOut,
  outputSchema: z.object({ file: z.string(), proposal: z.any() }),
  execute: async ({ inputData }) => {
    mkdirSync(inputData.out, { recursive: true });
    const file = join(inputData.out, 'prompt-revision-proposal.json');
    writeFileSync(file, JSON.stringify(
      { generated_at: new Date().toISOString(), root: inputData.root,
        proposal: inputData.proposal, note: '人の承認後に適用（自動適用しない）' },
      null, 2) + '\n');
    return { file, proposal: inputData.proposal };
  },
});

export const evalRevise = createWorkflow({
  id: 'eval-revise',
  inputSchema: EvalInput,
  outputSchema: z.object({ file: z.string(), proposal: z.any() }),
})
  .then(collectStep)
  .then(reviseStep)
  .then(proposeStep)
  .commit();
