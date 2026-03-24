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
  width: 100%;
  height: 100%;
}

body {
  background: #f5f7fa;
  overflow: hidden;
}

.app-shell {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
}

#app {
  min-height: 100%;
}
</style>
