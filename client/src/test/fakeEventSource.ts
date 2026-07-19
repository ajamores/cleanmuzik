/**
 * A controllable `EventSource` stand-in. jsdom ships none, and the behaviour
 * T-017 has to get right is entirely about *lifecycle* — which is invisible to a
 * click-through and is where three previous attempts were killed in review:
 *
 * - `track.review_required` is terminal for the stream; the panel opens a NEW
 *   EventSource after a resolve, and it must carry T-016's reconcile-on-death
 *   fallback rather than being a naive stream.
 * - `reject` and `keep_existing` emit NO terminal `track.*` event at all. The
 *   settle signal is stream-close plus a status snapshot. A naive stream
 *   reconnect-loops forever here, which is the bug the ticket names explicitly.
 *
 * So tests need to force a close, force an error, and replay named events on
 * demand. The real EventSource can do none of that on command.
 *
 * Install with `installFakeEventSource()` in a `beforeEach`; every instance the
 * code under test constructs is recorded on `.instances` in construction order.
 */

import { vi } from 'vitest'

export class FakeEventSource {
  static instances: FakeEventSource[] = []

  url: string
  readyState = 0 // CONNECTING
  closed = false
  onerror: ((ev: unknown) => void) | null = null
  onopen: ((ev: unknown) => void) | null = null
  onmessage: ((ev: unknown) => void) | null = null

  private listeners = new Map<string, Set<(ev: { data: string }) => void>>()

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(name: string, fn: (ev: { data: string }) => void) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set())
    this.listeners.get(name)!.add(fn)
  }

  removeEventListener(name: string, fn: (ev: { data: string }) => void) {
    this.listeners.get(name)?.delete(fn)
  }

  close() {
    this.closed = true
    this.readyState = 2 // CLOSED
  }

  /** Deliver a named SSE event, exactly as the server emits it. */
  emit(name: string, data: unknown) {
    const payload = typeof data === 'string' ? data : JSON.stringify(data)
    for (const fn of this.listeners.get(name) ?? []) fn({ data: payload })
  }

  /**
   * Simulate a dropped connection. The real EventSource fires `onerror` on every
   * failed retry, not once — so tests can call this repeatedly to prove the
   * fallback is guarded per-outage rather than per-error.
   */
  fail() {
    this.readyState = 0
    this.onerror?.(new Event('error'))
  }

  /** The most recently constructed instance — usually the one under test. */
  static latest(): FakeEventSource {
    const last = FakeEventSource.instances.at(-1)
    if (!last) throw new Error('no EventSource was constructed')
    return last
  }

  static reset() {
    FakeEventSource.instances = []
  }
}

export function installFakeEventSource() {
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
}
