/**
 * run.ts — eval→prompt改訂ワークフローを 1 回まわす。
 *
 *   bun run src/run.ts <content-root> [facet]
 *   例: bun run src/run.ts ~/.skills/suno-gen/albums parts
 *
 * 出力: <root>/../eval/prompt-revision-proposal.json（**自動適用しない**）
 */
import { evalRevise } from './mastra/workflows/evalRevise.ts';

const root = process.argv[2];
if (!root) {
  console.error('usage: bun run src/run.ts <content-root> [facet]');
  process.exit(1);
}
const facet = process.argv[3] ?? 'parts';

const run = await evalRevise.createRun();
const res: any = await run.start({ inputData: { root, facet } });
console.log(JSON.stringify(res?.result ?? res, null, 2));
