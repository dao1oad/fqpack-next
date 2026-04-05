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
) => ({
  ...detail,
  gaps: Array.isArray(workspace?.gaps) ? workspace.gaps : [],
  resolutions: Array.isArray(workspace?.resolutions) ? workspace.resolutions : [],
  rejections: Array.isArray(workspace?.rejections) ? workspace.rejections : [],
  reconciliationDetail: workspace?.detail || null,
  resolutionDataStatus,
})

const isNotFoundError = (error) => (
  Number(error?.response?.status || error?.status || 0) === 404
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
      try {
        workspace = await reconciliationApi.getSymbolWorkspace(symbol)
      } catch (error) {
        if (!isNotFoundError(error)) throw error
        resolutionDataStatus = 'workspace_endpoint_missing'
      }
      return mergeWorkspacePayload(detail, workspace, resolutionDataStatus)
    },
  }
}
