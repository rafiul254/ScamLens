import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// jsdom lacks these browser APIs; stub them so component tests can run.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// configurable so @testing-library/user-event can install its own clipboard stub
Object.defineProperty(navigator, 'clipboard', {
  value: { writeText: vi.fn().mockResolvedValue(undefined), readText: vi.fn().mockResolvedValue('') },
  writable: true,
  configurable: true,
})
