import fs from 'node:fs';
import path from 'node:path';
import { DEFAULT_CONFIG, type ContextMemConfig } from './types.js';

export function mergeConfig(partial: Record<string, unknown>): ContextMemConfig {
  const base = structuredClone(DEFAULT_CONFIG) as unknown as Record<string, unknown>;
  return deepMerge(base, partial) as unknown as ContextMemConfig;
}

export function loadConfig(projectDir: string): ContextMemConfig {
  const configPath = path.join(projectDir, '.context-mem.json');
  let config: ContextMemConfig;
  try {
    const raw = fs.readFileSync(configPath, 'utf8');
    const parsed = JSON.parse(raw);
    config = mergeConfig(parsed);
  } catch {
    config = structuredClone(DEFAULT_CONFIG);
  }
  // Allow environment variable to override db_path (works even without .context-mem.json)
  if (process.env.CONTEXT_MEM_DB_PATH) {
    config.db_path = process.env.CONTEXT_MEM_DB_PATH;
  }
  return config;
}

function deepMerge(target: Record<string, unknown>, source: Record<string, unknown>): Record<string, unknown> {
  for (const key of Object.keys(source)) {
    if (key === '__proto__' || key === 'constructor' || key === 'prototype') continue;
    const tVal = target[key];
    const sVal = source[key];
    if (sVal && typeof sVal === 'object' && !Array.isArray(sVal) && tVal && typeof tVal === 'object' && !Array.isArray(tVal)) {
      target[key] = deepMerge(tVal as Record<string, unknown>, sVal as Record<string, unknown>);
    } else {
      target[key] = sVal;
    }
  }
  return target;
}
