const toText = (value) => String(value || '').trim()

const normalizeList = (value) => (Array.isArray(value) ? value : [])

const resolvePlateRowKey = (plate) => {
  return toText(plate?.view_key || plate?.plate_key)
}

const normalizeWorkspaceItem = (row, plate) => {
  return {
    code6: toText(row?.code6 || row?.code),
    name: toText(row?.name),
    plate_key: toText(row?.plate_key || plate?.plate_key),
    plate_name: toText(row?.plate_name || plate?.plate_name),
    provider: toText(row?.provider || plate?.provider),
    hit_count_window: row?.hit_count_window ?? null,
    latest_trade_date: toText(row?.latest_trade_date),
  }
}

const buildReplacePayload = ({
  items = [],
  replaceScope = 'current_filter',
  stockWindowDays = 30,
  asOfDate = '',
  selectedExtraFilterKeys = [],
  plateKey = '',
} = {}) => {
  const seenCode6 = new Set()
  const dedupedItems = normalizeList(items).filter((item) => {
    if (!item.code6 || seenCode6.has(item.code6)) return false
    seenCode6.add(item.code6)
    return true
  })
  return {
    items: dedupedItems,
    replace_scope: replaceScope,
    days: Number(stockWindowDays) || 30,
    end_date: toText(asOfDate),
    selected_extra_filters: normalizeList(selectedExtraFilterKeys).map((value) => toText(value)).filter(Boolean),
    plate_key: toText(plateKey),
  }
}

export const buildCurrentFilterReplacePrePoolPayload = ({
  plates = [],
  stockRowsByPlate = {},
  stockWindowDays = 30,
  asOfDate = '',
  selectedExtraFilterKeys = [],
} = {}) => {
  const items = normalizeList(plates).flatMap((plate) => {
    const rowKey = resolvePlateRowKey(plate)
    return normalizeList(stockRowsByPlate?.[rowKey]).map((row) => normalizeWorkspaceItem(row, plate))
  })
  return buildReplacePayload({
    items,
    replaceScope: 'current_filter',
    stockWindowDays,
    asOfDate,
    selectedExtraFilterKeys,
  })
}

export const buildSinglePlateReplacePrePoolPayload = ({
  plate = null,
  stockRowsByPlate = {},
  stockWindowDays = 30,
  asOfDate = '',
  selectedExtraFilterKeys = [],
} = {}) => {
  const rowKey = resolvePlateRowKey(plate)
  const items = normalizeList(stockRowsByPlate?.[rowKey]).map((row) => normalizeWorkspaceItem(row, plate))
  return buildReplacePayload({
    items,
    replaceScope: 'single_plate',
    stockWindowDays,
    asOfDate,
    selectedExtraFilterKeys,
    plateKey: toText(plate?.plate_key),
  })
}

export const buildSinglePlateAppendPrePoolPayload = ({
  plate = null,
  stockRowsByPlate = {},
  stockWindowDays = 30,
  asOfDate = '',
  selectedExtraFilterKeys = [],
} = {}) => {
  const rowKey = resolvePlateRowKey(plate)
  const items = normalizeList(stockRowsByPlate?.[rowKey]).map((row) => normalizeWorkspaceItem(row, plate))
  return buildReplacePayload({
    items,
    replaceScope: 'single_plate',
    stockWindowDays,
    asOfDate,
    selectedExtraFilterKeys,
    plateKey: toText(plate?.plate_key),
  })
}

const mapWorkspaceRow = (
  item,
  {
    primaryActionLabel = '',
    secondaryActionLabel = '删除',
  } = {},
) => {
  return {
    code6: toText(item?.code6 || item?.code),
    name: toText(item?.name),
    category: toText(item?.category),
    plate_name: toText(item?.extra?.shouban30_plate_name),
    provider: toText(item?.extra?.shouban30_provider),
    primary_action_label: primaryActionLabel,
    secondary_action_label: secondaryActionLabel,
  }
}

export const buildWorkspaceTabs = ({
  prePoolItems = [],
  stockPoolItems = [],
} = {}) => {
  return [
    {
      key: 'pre_pool',
      label: 'pre_pools',
      batch_action_label: '同步到 stock_pool',
      sync_action_label: '同步到通达信',
      clear_action_label: '清空',
      rows: normalizeList(prePoolItems).map((item) => mapWorkspaceRow(item, {
        primaryActionLabel: '加入 stock_pools',
      })),
    },
    {
      key: 'stockpools',
      label: 'stock_pools',
      batch_action_label: '同步到 must_pools',
      sync_action_label: '同步到通达信',
      clear_action_label: '清空',
      rows: normalizeList(stockPoolItems).map((item) => mapWorkspaceRow(item, {
        primaryActionLabel: '加入 must_pools',
      })),
    },
  ]
}

export const resolveSelectedStockDetailContext = ({
  selectedStockCode6 = '',
  currentStocks = [],
  workspaceTabs = [],
} = {}) => {
  const code6 = toText(selectedStockCode6)
  if (!code6) return null

  const currentStock = normalizeList(currentStocks)
    .find((item) => toText(item?.code6) === code6)
  if (currentStock) {
    return {
      code6,
      name: toText(currentStock?.name) || code6,
      provider: toText(currentStock?.provider),
      plate_name: toText(currentStock?.plate_name),
    }
  }

  const workspaceRow = normalizeList(workspaceTabs)
    .flatMap((tab) => normalizeList(tab?.rows))
    .find((item) => toText(item?.code6) === code6)
  if (workspaceRow) {
    return {
      code6,
      name: toText(workspaceRow?.name) || code6,
      provider: toText(workspaceRow?.provider),
      plate_name: toText(workspaceRow?.plate_name),
    }
  }

  return {
    code6,
    name: code6,
    provider: '',
    plate_name: '',
  }
}
