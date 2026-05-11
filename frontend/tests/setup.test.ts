import { describe, it, expect } from 'vitest'

describe('Frontend Setup', () => {
  it('should pass basic test', () => {
    expect(true).toBe(true)
  })

  it('should have correct environment', () => {
    expect(typeof window).toBe('object')
    expect(typeof document).toBe('object')
  })
})
