// Test helper: the API's committed golden responses (docs/contracts/golden/pi-api).
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

export const GOLDEN_DIR = join(__dirname, '../../../../docs/contracts/golden/pi-api');

export function goldenNames(): string[] {
  return readdirSync(GOLDEN_DIR)
    .filter((f) => f.endsWith('.json'))
    .map((f) => f.slice(0, -5));
}

export function golden(name: string): unknown {
  return JSON.parse(readFileSync(join(GOLDEN_DIR, `${name}.json`), 'utf8'));
}
