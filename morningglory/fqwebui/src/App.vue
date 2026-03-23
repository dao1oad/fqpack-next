<template>
  <div class="app-shell">
    <router-view />
  </div>
</template>

<style>
html,
body,
#app {
  margin: 0;
  min-height: 100%;
}

body {
  background: #f5f7fa;
  overflow-x: auto;
  overflow-y: auto;
}

#app,
.app-shell {
  min-height: 100%;
}
</style>
