const toArray = (value) => Array.isArray(value) ? value : []

const normalizeOptions = (options = []) => {
  return toArray(options).map((item) => {
    if (typeof item === 'object' && item !== null) {
      return {
        value: item.value,
        label: item.label ?? String(item.value ?? ''),
      }
    }
    return {
      value: item,
      label: String(item ?? ''),
    }
  })
}

export const buildDailyScreeningForms = (schema = {}) => {
  const models = toArray(schema.models)
  return Object.fromEntries(
    models.map((model) => [
      model.id,
      Object.fromEntries(
        toArray(model.fields).map((field) => [field.name, field.default ?? '']),
      ),
    ]),
  )
}

export const resolveDailyScreeningFields = (schema = {}, modelId, form = {}) => {
  const model = toArray(schema.models).find((item) => item.id === modelId)
  if (!model) return []

  return toArray(model.fields)
    .filter((field) => {
      if (modelId !== 'chanlun') return true
      if (field.name === 'code') return form.input_mode === 'single_code'
      if (field.name === 'pre_pool_category') return form.input_mode === 'category_filtered_pre_pools'
      if (field.name === 'pre_pool_remark') return form.input_mode === 'remark_filtered_pre_pools'
      if (field.name === 'pool_expire_days') return Boolean(form.save_pools)
      return true
    })
    .map((field) => {
      if (field.name === 'pre_pool_category') {
        return {
          ...field,
          options: normalizeOptions(
            toArray(schema.options?.pre_pool_categories).map((value) => ({
              value,
              label: value,
            })),
          ),
        }
      }
      if (field.name === 'pre_pool_remark') {
        return {
          ...field,
          options: normalizeOptions(
            toArray(schema.options?.pre_pool_remarks).map((value) => ({
              value,
              label: value,
            })),
          ),
        }
      }
      return {
        ...field,
        options: normalizeOptions(field.options),
      }
    })
}

export const buildDailyScreeningCliPreview = (modelId, form = {}) => {
  if (modelId === 'all') {
    const clxsCommands = toArray(form.clxs_model_opts).map((modelOpt) => (
      [
        'stock screen clxs',
        `--days ${form.days ?? 1}`,
        form.code ? `--code ${form.code}` : '',
        `--wave-opt ${form.wave_opt ?? 1560}`,
        `--stretch-opt ${form.stretch_opt ?? 0}`,
        `--trend-opt ${form.trend_opt ?? 1}`,
        `--model-opt ${modelOpt}`,
      ].filter(Boolean).join(' ')
    ))
    const chanlunParts = [
      'stock screen chanlun',
      `--days ${form.days ?? 1}`,
      form.chanlun_period_mode && form.chanlun_period_mode !== 'all'
        ? `--period ${form.chanlun_period_mode}`
        : '',
      form.code ? `--code ${form.code}` : '',
    ].filter(Boolean)

    return {
      command: [...clxsCommands, chanlunParts.join(' ')].filter(Boolean).join('\n'),
      extensions: [
        'chanlun_source=current_clxs_run',
        `chanlun_signal_types=${toArray(form.chanlun_signal_types).join(',')}`,
      ].filter(Boolean),
    }
  }

  if (modelId === 'clxs') {
    const modelOpts = toArray(form.model_opts).length
      ? toArray(form.model_opts)
      : [form.model_opt ?? 10001]
    const parts = modelOpts.map((modelOpt) => [
      'stock screen clxs',
      `--days ${form.days ?? 1}`,
      form.code ? `--code ${form.code}` : '',
      `--wave-opt ${form.wave_opt ?? 1560}`,
      `--stretch-opt ${form.stretch_opt ?? 0}`,
      `--trend-opt ${form.trend_opt ?? 1}`,
      `--model-opt ${modelOpt}`,
    ].filter(Boolean).join(' '))

    return {
      command: parts.join('\n'),
      extensions: form.remark ? [`remark=${form.remark}`] : [],
    }
  }

  const parts = [
    'stock screen chanlun',
    `--days ${form.days ?? 1}`,
    form.period_mode && form.period_mode !== 'all' ? `--period ${form.period_mode}` : '',
    form.code && form.input_mode === 'single_code' ? `--code ${form.code}` : '',
  ].filter(Boolean)

  const extensions = []
  if (form.input_mode && form.input_mode !== 'single_code') {
    extensions.push(`input_mode=${form.input_mode}`)
  }
  if (form.pre_pool_category && form.input_mode === 'category_filtered_pre_pools') {
    extensions.push(`pre_pool_category=${form.pre_pool_category}`)
  }
  if (form.pre_pool_remark && form.input_mode === 'remark_filtered_pre_pools') {
    extensions.push(`pre_pool_remark=${form.pre_pool_remark}`)
  }
  if (form.max_concurrent != null) {
    extensions.push(`max_concurrent=${form.max_concurrent}`)
  }
  if (form.save_signal) {
    extensions.push('save_signal=true')
  }
  if (form.save_pools) {
    extensions.push('save_pools=true')
    extensions.push(`pool_expire_days=${form.pool_expire_days ?? 10}`)
  }
  if (form.remark) {
    extensions.push(`remark=${form.remark}`)
  }

  return {
    command: parts.join(' '),
    extensions,
  }
}

export const getDailyScreeningGuide = (modelId) => {
  if (modelId === 'all') {
    return [
      '先跑 CLXS 全模型，再用本次 CLXS 落库结果作为 chanlun 输入源。',
      'CLXS 全模型默认包含 MACD 背驰、中枢回拉、V 反、默认 CLXS。',
      'chanlun 默认保留 6 个固定信号，并保留 signal_type + period 粒度供二次筛选。',
      '页面二次选择不再重新扫描，而是直接基于本次 accepted / pre_pool 结果按模型按钮过滤。',
    ]
  }
  if (modelId === 'clxs') {
    return [
      '过滤全市场 ST 股票，默认扫日线。',
      '核心命中条件是 sigs[-1] > 0。',
      '止损价取最近笔底最低价。',
      '结果按 code + fire_date 去重，再决定是否落库 pre_pools。',
    ]
  }
  return [
    '默认周期为 30m / 60m / 1d，可在页面改成单周期。',
    '实际启用的是回拉中枢、V 反、MACD 背驰 6 个固定信号。',
    '最终只保留最近 N 天且方向为 BUY_LONG 的结果。',
    '当输入来自共享 pre_pools 时，可以按 category 或 remark 过滤来源。',
  ]
}

export const normalizeDailyScreeningRow = (row = {}) => {
  const branch = row.branch
    || row.extra?.screening_branch
    || (String(row.signal_type || '').startsWith('CLXS_') ? 'clxs' : 'chanlun')
  const modelKey = row.model_key
    || row.extra?.screening_model_key
    || row.signal_type
    || ''
  const modelLabel = row.model_label
    || row.extra?.screening_model_label
    || row.signal_name
    || row.remark
    || modelKey

  return {
    ...row,
    branch,
    model_key: modelKey,
    model_label: modelLabel,
  }
}

export const buildDailyScreeningModelFilters = (rows = [], selectedBranch = 'all') => {
  const normalizedRows = toArray(rows).map((row) => normalizeDailyScreeningRow(row))
  const branchMap = new Map()
  const modelMap = new Map()

  normalizedRows.forEach((row) => {
    if (row.branch && !branchMap.has(row.branch)) {
      branchMap.set(row.branch, {
        key: row.branch,
        label: row.branch === 'clxs' ? 'CLXS' : 'chanlun',
        count: 0,
      })
    }
    if (row.branch && branchMap.has(row.branch)) {
      branchMap.get(row.branch).count += 1
    }
    if (selectedBranch !== 'all' && row.branch !== selectedBranch) {
      return
    }
    if (row.model_key && !modelMap.has(row.model_key)) {
      modelMap.set(row.model_key, {
        key: row.model_key,
        label: row.model_label || row.model_key,
        branch: row.branch,
        count: 0,
      })
    }
    if (row.model_key && modelMap.has(row.model_key)) {
      modelMap.get(row.model_key).count += 1
    }
  })

  return {
    branches: [...branchMap.values()],
    models: [...modelMap.values()],
  }
}

export const applyDailyScreeningRowFilters = (rows = [], filters = {}) => {
  const branch = filters.branch || 'all'
  const modelKey = filters.modelKey || 'all'
  return toArray(rows)
    .map((row) => normalizeDailyScreeningRow(row))
    .filter((row) => {
      if (branch !== 'all' && row.branch !== branch) return false
      if (modelKey !== 'all' && row.model_key !== modelKey) return false
      return true
    })
}
