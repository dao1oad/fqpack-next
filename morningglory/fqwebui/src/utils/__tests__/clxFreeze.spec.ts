import { describe, expect, it } from 'vitest'
import { buildFrozenRankDigest, canonicalJson, contentHash, DEFAULT_CLX_RANKING_CONFIG } from '@/utils/clxFreeze'

describe('CLX 冻结哈希', () => {
  it('与后端 ensure_ascii=False / sort_keys canonical JSON 一致', async () => {
    expect(canonicalJson({ b: '中', a: 1 })).toBe('{"a":1,"b":"中"}')
    await expect(contentHash({ b: '中', a: 1 })).resolves.toBe(
      'sha256:2831299868169bc527f55f88ebbdcd8b785d78d9e7dc64e6887dfbd2825dd247',
    )
  })

  it('将完整 VALIDATION 顺序和 ranking_config 绑定进 digest', async () => {
    const config = { ...DEFAULT_CLX_RANKING_CONFIG, horizon: 5 }
    const first = await buildFrozenRankDigest('RUN_1', ['C1', 'C2'], config)
    const reordered = await buildFrozenRankDigest('RUN_1', ['C2', 'C1'], config)
    expect(first.rankingConfigSha256).toMatch(/^sha256:[0-9a-f]{64}$/)
    expect(first.frozenRankDigest).not.toBe(reordered.frozenRankDigest)
  })
})
