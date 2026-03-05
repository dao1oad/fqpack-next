export default {
  // 设置当前语言
  SET_LANG (state, lang) {
    state.lang = lang
    lang ? window.localStorage.setItem('lang', lang) : window.localStorage.removeItem('lang')
  }
}
