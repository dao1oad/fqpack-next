import type { Component } from 'vue'
import { mount, type MountingOptions } from '@vue/test-utils'
import ElementPlus from 'element-plus'

export function mountWithProviders(component: Component, props: Record<string, unknown> = {}, options: MountingOptions<any> = {}) {
  return mount(component, {
    ...options,
    props,
    attachTo: document.body,
    global: { plugins: [ElementPlus], ...(options.global ?? {}) },
  })
}
