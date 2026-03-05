const _M = {}

_M.getStyle = function (element) {
  if (window.getComputedStyle) {
    return window.getComputedStyle(element, null)
  } else {
    return element.currentStyle
  }
}

_M.fitToContainerSize = function (element, container) {
  const containerStyle = _M.getStyle(container)
  element.style.height = containerStyle.height
  element.style.width = containerStyle.width
}

export default _M
