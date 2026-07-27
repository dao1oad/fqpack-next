import { sha256 } from '@noble/hashes/sha2.js'
import { bytesToHex } from '@noble/hashes/utils.js'

export const DEFAULT_CLX_RANKING_CONFIG: Record<string, unknown> = {
  horizon: 5,
  min_train_sample: 100,
  min_validation_sample: 50,
  min_train_density: 0.01,
  min_validation_density: 0.005,
  min_train_years: 2,
  min_validation_years: 1,
  min_events_per_year: 3,
  max_train_fdr: 0.2,
  max_validation_fdr: 0.2,
  beam_width_per_stage: 64,
  max_candidates_per_stage: 4096,
  max_total_candidates: 16384,
  max_seed_per_root: 2,
  max_trigger_terms: 2,
  jaccard_threshold: 0.95,
  resonance_lookbacks: [0, 1, 3, 5],
  enable_sequences: true,
  train_score_weights: [
    ['ci_low', 0.5],
    ['complexity', -0.001],
    ['density', 0.001],
    ['mean_return', 1],
    ['win_rate_edge', 0.2],
    ['year_positive_ratio', 0.1],
  ],
  validation_score_weights: [
    ['ci_low', 0.5],
    ['complexity', -0.001],
    ['density', 0.001],
    ['mean_return', 1],
    ['retention', 0.1],
    ['stability', 0.1],
    ['win_rate_edge', 0.2],
    ['year_positive_ratio', 0.1],
  ],
}

function canonicalValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalValue)
  if (value && typeof value === 'object') {
    return Object.keys(value as Record<string, unknown>).sort().reduce<Record<string, unknown>>((result, key) => {
      result[key] = canonicalValue((value as Record<string, unknown>)[key])
      return result
    }, {})
  }
  return value
}

export function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalValue(value))
}

export async function contentHash(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJson(value))
  return `sha256:${bytesToHex(sha256(bytes))}`
}

export async function buildFrozenRankDigest(
  runId: string,
  rankOrder: string[],
  rankingConfig: Record<string, unknown>,
): Promise<{ rankingConfigSha256: string; frozenRankDigest: string }> {
  const rankingConfigSha256 = await contentHash(rankingConfig)
  const frozenRankDigest = await contentHash({
    run_id: runId,
    split_id: 'VALIDATION',
    rank_order: rankOrder,
    ranking_config_sha256: rankingConfigSha256,
  })
  return { rankingConfigSha256, frozenRankDigest }
}
