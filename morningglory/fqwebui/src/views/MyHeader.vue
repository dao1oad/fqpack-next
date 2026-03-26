<template>
  <div class="header-main">
    <div class="header-menu">
      <el-button-group v-for="(group, groupIndex) in headerNavGroups" :key="`header-group-${groupIndex}`">
        <el-button
          v-for="item in group"
          :key="item.key"
          :type="item.buttonType"
          :plain="item.plain"
          :size="item.size"
          @click="openNavTab(item.key)"
        >
          {{ item.label }}
        </el-button>
      </el-button-group>
    </div>
    <div class="header-tip">
      <span>顺势而为 抓大放小 以小博大 提高胜率比（双盘|二买|完备|三买）</span>
    </div>
  </div>
</template>

<script>
import {
  HEADER_NAV_GROUPS,
  HEADER_NAV_TARGETS,
  getHeaderNavTarget,
} from '@/router/pageMeta.mjs'

export default {
  name: 'my-header',
  computed: {
    headerNavGroups() {
      return HEADER_NAV_GROUPS.map((group) => group
        .map((key) => {
          const meta = HEADER_NAV_TARGETS[key] || {}
          const target = getHeaderNavTarget(key)
          if (!target) return null

          return {
            ...target,
            key,
            buttonType: meta.buttonType || 'default',
            plain: Boolean(meta.plain),
            size: meta.size || 'small',
          }
        })
        .filter(Boolean))
    },
  },
  methods: {
    openNavTab(type) {
      const target = getHeaderNavTarget(type)
      if (!target) return

      const routeUrl = this.$router.resolve({
        path: target.path,
        query: target.query,
      })

      window.open(routeUrl.href, '_blank', 'noopener')
    },
  },
}
</script>

<style lang="stylus">
@import "../style/my-header.styl";
</style>
