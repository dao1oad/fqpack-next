import { createOrderManagementActions } from './orderManagement.mjs'
import {
  buildPositionReconciliationRows,
  buildPositionReconciliationSummaryViewModel,
} from './positionReconciliation.mjs'
import { createTpslManagementActions } from './tpslManagement.mjs'

const mergeWorkspacePayload = (
  detail = {},
  workspace = {},
  resolutionDataStatus = 'loaded',
  resolutionErrorMessage = '',
) => ({
  ...detail,
  gaps: Array.isArray(workspace?.gaps) ? workspace.gaps : [],
  resolutions: Array.isArray(workspace?.resolutions) ? workspace.resolutions : [],
  rejections: Array.isArray(workspace?.rejections) ? workspace.rejections : [],
  reconciliationDetail: workspace?.detail || null,
  resolutionDataStatus,
  resolutionErrorMessage: String(resolutionErrorMessage || '').trim(),
})

const isNotFoundError = (error) => (
  Number(error?.response?.status || error?.status || 0) === 404
)

const getWorkspaceNotFoundStatus = (error) => {
  if (!isNotFoundError(error)) return ''
  const responseMessage = String(error?.response?.data?.error || '').trim().toLowerCase()
  if (responseMessage.includes('not tracked')) return 'workspace_symbol_not_tracked'
  return 'workspace_endpoint_missing'
}

const getErrorMessage = (error) => (
  String(error?.response?.data?.error || error?.message || '').trim()
)

export const createReconciliationWorkbenchActions = ({
  positionApi,
  orderApi,
  tpslApi,
  reconciliationApi,
} = {}) => {
  const orderActions = createOrderManagementActions(orderApi)
  const tpslActions = createTpslManagementActions(tpslApi)

  return {
    async loadOverview() {
      const response = await positionApi.getReconciliation()
      const summaryViewModel = buildPositionReconciliationSummaryViewModel(response)
      return {
        summary: summaryViewModel.summary,
        stateCards: summaryViewModel.stateCards,
        ruleCards: summaryViewModel.ruleCards,
        rows: buildPositionReconciliationRows(response),
      }
    },
    async loadOrders(filters = {}) {
      return orderActions.loadOrders(filters)
    },
    async loadOrderDetail(orderId) {
      return orderActions.loadOrderDetail(orderId)
    },
    async loadOrderStats(filters = {}) {
      return orderActions.loadStats(filters)
    },
    async loadSymbolWorkspace(symbol) {
      const detail = await tpslActions.loadSymbolDetail(symbol)
      if (!reconciliationApi || typeof reconciliationApi.getSymbolWorkspace !== 'function') {
        return mergeWorkspacePayload(detail, {}, 'workspace_api_unconfigured')
      }
      let workspace = null
      let resolutionDataStatus = 'loaded'
      let resolutionErrorMessage = ''
      try {
        workspace = await reconciliationApi.getSymbolWorkspace(symbol)
      } catch (error) {
        if (!isNotFoundError(error)) throw error
        resolutionDataStatus = getWorkspaceNotFoundStatus(error) || 'workspace_endpoint_missing'
        resolutionErrorMessage = getErrorMessage(error)
      }
      return mergeWorkspacePayload(
        detail,
        workspace,
        resolutionDataStatus,
        resolutionErrorMessage,
      )
    },
  }
}
