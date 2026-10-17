#!/usr/bin/env node
import { readFileSync, writeFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const directory = process.argv[2] || 'benchmarks/codex-rp/results';
const quantile = (values, q) => {
  if (!values.length) return null;
  const ordered = [...values].sort((a, b) => a - b);
  if (q === 0.5 && ordered.length % 2 === 0) return (ordered[ordered.length / 2 - 1] + ordered[ordered.length / 2]) / 2;
  return ordered[Math.max(0, Math.ceil(q * ordered.length) - 1)];
};
const summary = [];
let total = 0;
for (const run of readdirSync(directory, { withFileTypes: true }).filter(d => d.isDirectory()).map(d => d.name)) {
  const path = join(directory, run, 'trials.jsonl');
  if (!existsSync(path)) continue;
  const rows = readFileSync(path, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse);
  total += rows.length;
  const rejectedTiers = new Set(rows.filter(r => r.configuredTier !== undefined && r.tier !== 'default' &&
    r.configuredTier !== (r.tier === 'fast' ? 'priority' : r.tier))
    .map(r => JSON.stringify([r.variant || r.model, r.tier])));
  const groups = new Map();
  for (const row of rows) {
    const key = JSON.stringify([row.variant || row.model, row.effort, row.tier, row.scenario || 'availability', !!row.warmup]);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  for (const [key, rows] of groups) {
    const [variant, effort, tier, scenario, warmup] = JSON.parse(key);
    const successful = rows.filter(r => r.status === 'completed' && r.text?.trim());
    const full = successful.map(r => r.lastTextMs).filter(Number.isFinite);
    const first = successful.map(r => r.firstTextMs).filter(Number.isFinite);
    const complete = successful.map(r => r.completedMs).filter(Number.isFinite);
    const tierAccepted = !rejectedTiers.has(JSON.stringify([variant, tier]));
    summary.push({ run, variant, effort, tier, tierAccepted, scenario, warmup,
      trials: rows.length, successful: successful.length,
      firstMedianMs: quantile(first, 0.5), fullMedianMs: quantile(full, 0.5),
      fullP95Ms: quantile(full, 0.95), fullMaxMs: full.length ? Math.max(...full) : null,
      completeMedianMs: quantile(complete, 0.5), completeMaxMs: complete.length ? Math.max(...complete) : null,
      fullUnder2s: successful.filter(r => r.lastTextMs < 2000).length,
      completeUnder2s: successful.filter(r => r.completedMs < 2000).length,
      errors: rows.flatMap(r => [...(r.errors || []), ...(r.error ? [r.error] : [])]),
    });
  }
}
writeFileSync(join(directory, 'summary.json'), JSON.stringify({
  generatedAt: new Date().toISOString(), totalTrials: total,
  quantiles: 'median, nearest-rank sample p95; these small samples do not establish a production percentile or SLA',
  groups: summary,
}, null, 2) + '\n');
const headings = ['run', 'variant', 'effort', 'tier', 'tierAccepted', 'scenario', 'warmup', 'trials',
  'successful', 'firstMedianMs', 'fullMedianMs', 'fullP95Ms', 'fullMaxMs', 'completeMedianMs',
  'completeMaxMs', 'fullUnder2s', 'completeUnder2s'];
const csv = [headings.join(','), ...summary.map(row => headings.map(k => JSON.stringify(row[k] ?? '')).join(','))];
writeFileSync(join(directory, 'summary.csv'), csv.join('\n') + '\n');
console.log(JSON.stringify({ totalTrials: total, groups: summary.length, summary: join(directory, 'summary.json') }));
