export const lang = state => {
  if (state.lang) {
    return state.lang
  } else {
    return localStorage.getItem('lang') || 'zh-CN'
  }
}
