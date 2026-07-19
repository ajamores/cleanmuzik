import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Unmount between tests. Without this a component's `useEffect` cleanup never
// runs, so an open EventSource stub leaks into the next test and its handlers
// fire against a torn-down tree — which reads as a flaky test rather than the
// missing teardown it is.
afterEach(cleanup)
