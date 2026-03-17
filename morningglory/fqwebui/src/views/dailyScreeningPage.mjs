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
  if (modelId === 'clxs') {
    const parts = [
      'stock screen clxs',
      `--days ${form.days ?? 1}`,
      form.code ? `--code ${form.code}` : '',
      `--wave-opt ${form.wave_opt ?? 1560}`,
      `--stretch-opt ${form.stretch_opt ?? 0}`,
      `--trend-opt ${form.trend_opt ?? 1}`,
      `--model-opt ${form.model_opt ?? 10001}`,
    ].filter(Boolean)

    return {
      command: parts.join(' '),
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
