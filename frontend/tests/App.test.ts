import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import App from '../src/App.vue'
import router from '../src/router'

describe('App.vue', () => {
  it('should render app container', () => {
    const wrapper = mount(App, {
      global: {
        stubs: {
          RouterView: true
        }
      }
    })
    expect(wrapper.find('#app').exists()).toBe(true)
  })

  it('should render without router errors', async () => {
    const wrapper = mount(App, {
      global: {
        plugins: [router]
      }
    })
    await router.isReady()
    expect(wrapper.html()).toBeTruthy()
    expect(wrapper.html()).not.toContain('404')
  })
})
