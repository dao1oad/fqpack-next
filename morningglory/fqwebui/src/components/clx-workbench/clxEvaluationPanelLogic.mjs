const toText = (value) => String(value ?? '').trim()

export const LATEST_EVALUATION_ENDPOINT = '/data/clx-evaluator/latest.json'

const loadHttp = async () => (await import('@/http')).default

export const normalizeEvaluation = (latest = {}, snapshot = null) => {
  const data = snapshot || {}
  const summary = data.summary || {}
  const review = data.review || {}
  const manifest = data.sourceManifest || {}
  const evaluatedBatchId = toText(
    data.clxBatchId ||
      data.batchId ||
      data.scopeId ||
      manifest.clxBatchId ||
      manifest.batchId ||
      latest.clxBatchId ||
      '',
  )
  return {
    status: data && Object.keys(data).length ? 'ready' : 'pending',
    tradeDate: toText(data.tradeDate || latest.tradeDate),
    runId: toText(data.runId || latest.runId),
    href: toText(latest.href),
    evaluatedBatchId,
    evaluatedPublicationId: toText(
      data.publicationId ||
        data.clxPublicationId ||
        manifest.publicationId ||
        '',
    ),
    evaluatedContentHash: toText(
      data.officialContentHash ||
        data.contentHash ||
        manifest.officialContentHash ||
        '',
    ),
    generatedAt: toText(review.generatedAt || latest.promotedAt || latest.generatedAt),
    summary: {
      stockRows: Number(summary.stockRows ?? 0),
      groupCount: Number(summary.groupCount ?? 0),
      remainingUnmapped: Number(summary.remainingUnmapped ?? 0),
      fundamentalEvidenceGap: Number(summary.fundamentalEvidenceGap ?? 0),
      mappedEtfCount: Number(summary.mappedEtfCount ?? 0),
    },
    groups: Array.isArray(data.groups) ? data.groups : [],
    members: Array.isArray(data.members) ? data.members : [],
    sellDiagnostics: Array.isArray(data.diagnostics?.sellDiagnostics)
      ? data.diagnostics.sellDiagnostics
      : [],
  }
}

export const fetchEvaluation = async ({ fetcher = null } = {}) => {
  await loadHttp()
  const doFetch =
    fetcher ||
    (async () => {
      const latestResponse = await fetch(LATEST_EVALUATION_ENDPOINT)
      if (!latestResponse.ok) {
        throw new Error(`latest.json HTTP ${latestResponse.status}`)
      }
      const latest = await latestResponse.json()
      if (!toText(latest.href)) {
        return normalizeEvaluation(latest, null)
      }
      const snapshotResponse = await fetch(latest.href)
      if (!snapshotResponse.ok) {
        throw new Error(`clx-eval.v1.json HTTP ${snapshotResponse.status}`)
      }
      const snapshot = await snapshotResponse.json()
      return normalizeEvaluation(latest, snapshot)
    })
  return doFetch()
}

export const filterEvaluationGroups = (groups = [], keyword = '') => {
  const q = toText(keyword).toLowerCase()
  if (!q) return groups
  return groups.filter((group) =>
    [
      group.groupName,
      group.marketLane,
      group.themeId,
    ].some((value) => String(value || '').toLowerCase().includes(q)),
  )
}

export const filterEvaluationMembers = (
  members = [],
  { q = '', groupName = '', primaryGroup = '', marketLane = '', shortlistEligible = '' } = {},
) => {
  const query = toText(q).toLowerCase()
  return members
    .filter((member) => {
      if (
        query &&
        ![member.symbol, member.name, member.primaryGroup].some((value) =>
          String(value || '').toLowerCase().includes(query),
        )
      ) {
        return false
      }
      if (toText(groupName) && member.primaryGroup !== toText(groupName)) return false
      if (toText(primaryGroup) && member.primaryGroup !== toText(primaryGroup)) return false
      if (toText(marketLane) && member.marketLane !== toText(marketLane)) return false
      if (
        toText(shortlistEligible) &&
        String(Boolean(member.shortlistEligible)) !== toText(shortlistEligible)
      ) {
        return false
      }
      return true
    })
    .slice()
    .sort((a, b) => Number(a.globalRank ?? 0) - Number(b.globalRank ?? 0))
}

export const buildEvaluationTdxItems = (members = []) =>
  members.map((member) => ({
    asset_type: 'stock',
    symbol: toText(member.symbol),
  }))

export const buildEvaluationExportPayload = (evaluation = {}, members = []) => {
  const batchId = toText(evaluation.evaluatedBatchId)
  if (!batchId) return null
  return {
    batchId,
    items: buildEvaluationTdxItems(members),
  }
}

export const formatEvaluationTime = (value) => {
  const text = toText(value)
  return text || '—'
}
