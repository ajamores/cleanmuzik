/**
 * AcquireDial — the round detented acquire-intent selector (ADR-029, T-310 gate D1–D4).
 *
 * It looks like a knob but is an ARIA radiogroup: the point of these tests is the
 * *interaction contract*, not the ornament. Single is the resting default; clicks and
 * arrow keys move between stops and check as they land; Multi is a present-but-inert stop
 * that is selectable for preview but which the parent never submits.
 */

import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AcquireDial, type DialMode } from './AcquireDial'

function renderDial(mode: DialMode = 'single') {
  const onChange = vi.fn()
  const utils = render(<AcquireDial mode={mode} onChange={onChange} />)
  const group = screen.getByRole('radiogroup', { name: /acquire mode/i })
  return { onChange, group, ...utils }
}

describe('AcquireDial', () => {
  it('is a radiogroup with three stops; Single is checked by default', () => {
    const { group } = renderDial('single')
    const radios = within(group).getAllByRole('radio')
    expect(radios).toHaveLength(3)
    expect(within(group).getByRole('radio', { name: 'Single' })).toBeChecked()
    expect(within(group).getByRole('radio', { name: 'Playlist' })).not.toBeChecked()
  })

  it('reflects the mode prop on the group (drives the pointer angle in CSS)', () => {
    const { group } = renderDial('playlist')
    expect(group).toHaveAttribute('data-mode', 'playlist')
    expect(within(group).getByRole('radio', { name: 'Playlist' })).toBeChecked()
  })

  it('clicking a stop selects it', () => {
    const { onChange, group } = renderDial('single')
    fireEvent.click(within(group).getByRole('radio', { name: 'Playlist' }))
    expect(onChange).toHaveBeenCalledWith('playlist')
  })

  it('arrow keys walk the stops and select as they land', () => {
    const { onChange, group } = renderDial('single')
    const single = within(group).getByRole('radio', { name: 'Single' })
    fireEvent.keyDown(single, { key: 'ArrowRight' })
    expect(onChange).toHaveBeenCalledWith('playlist')
  })

  it('arrow keys wrap at the ends', () => {
    const { onChange, group } = renderDial('single')
    // Left from the first stop wraps to the last (Multi).
    fireEvent.keyDown(within(group).getByRole('radio', { name: 'Single' }), {
      key: 'ArrowLeft',
    })
    expect(onChange).toHaveBeenCalledWith('multi')
  })

  it('Home/End jump to the first/last stop', () => {
    const { onChange, group } = renderDial('playlist')
    fireEvent.keyDown(within(group).getByRole('radio', { name: 'Playlist' }), { key: 'End' })
    expect(onChange).toHaveBeenLastCalledWith('multi')
    fireEvent.keyDown(within(group).getByRole('radio', { name: 'Playlist' }), { key: 'Home' })
    expect(onChange).toHaveBeenLastCalledWith('single')
  })

  it('the roving tabindex sits on the checked stop only', () => {
    const { group } = renderDial('playlist')
    expect(within(group).getByRole('radio', { name: 'Playlist' })).toHaveAttribute('tabindex', '0')
    expect(within(group).getByRole('radio', { name: 'Single' })).toHaveAttribute('tabindex', '-1')
  })

  it('Multi is present, labelled "coming soon", and selectable for preview', () => {
    const { onChange, group } = renderDial('single')
    const multi = within(group).getByRole('radio', { name: /coming soon/i })
    expect(multi).toBeInTheDocument()
    fireEvent.click(multi)
    // It IS selectable (to preview the "soon" panel); the parent decides not to submit it.
    expect(onChange).toHaveBeenCalledWith('multi')
  })

  it('a non-navigation key is ignored', () => {
    const { onChange, group } = renderDial('single')
    fireEvent.keyDown(within(group).getByRole('radio', { name: 'Single' }), { key: 'a' })
    expect(onChange).not.toHaveBeenCalled()
  })
})
