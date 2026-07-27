class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
Object.defineProperty(globalThis, 'ResizeObserver', { value: ResizeObserverMock, writable: true })
Object.defineProperty(window, 'matchMedia', {
  configurable: true,
  writable: true,
  value: query => ({
    matches: false, media: query, onchange: null,
    addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false },
  }),
})
Object.defineProperty(navigator, 'clipboard', { value: { async writeText() {} }, configurable: true })
Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
  configurable: true,
  value: () => ({ width: 1024, height: 600, top: 0, left: 0, right: 1024, bottom: 600, x: 0, y: 0, toJSON: () => ({}) }),
})
window.open = () => null
