import {
  buildSidebarSections as buildLegacySidebarSections,
  getReasonPanelMessage,
  getSidebarCode6,
  getSidebarDeleteBehavior,
  normalizeReasonItems,
  toggleSidebarExpandedKey,
} from './js/kline-slim-sidebar.mjs'

const normalizeBridgeSidebarItem = (item = {}) => ({
  ...item,
  titleLabel: item.titleLabel || '',
  secondaryLabel: item.secondaryLabel || '',
})

export const buildSidebarSections = (options = {}) => {
  return buildLegacySidebarSections(options).map((section) => ({
    ...section,
    items: Array.isArray(section.items)
      ? section.items.map((item) => normalizeBridgeSidebarItem(item))
      : [],
  }))
}

export {
  getReasonPanelMessage,
  getSidebarCode6,
  getSidebarDeleteBehavior,
  normalizeReasonItems,
  toggleSidebarExpandedKey,
}
