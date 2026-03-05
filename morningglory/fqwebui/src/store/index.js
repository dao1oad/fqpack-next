import { createStore } from 'vuex'
import * as getters from './getters'
import mutations from './mutations'

export default createStore({
  state: {
    lang: ''
  },
  getters,
  mutations,
  actions: {
  },
  modules: {
  }
})
