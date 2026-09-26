import { Mastra } from '@mastra/core';
import { reviser } from './agents/reviser.ts';
import { evalRevise } from './workflows/evalRevise.ts';

export const mastra = new Mastra({
  agents: { reviser },
  workflows: { evalRevise },
});
