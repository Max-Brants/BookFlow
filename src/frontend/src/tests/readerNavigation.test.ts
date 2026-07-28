import { describe, expect, it } from 'vitest';

import { keyboardNavigationAction, tapZoneAction } from '../reader/readerNavigation';

describe('reader navigation', () => {
  it('uses the outer quarters for page turns and the centre to reveal controls', () => {
    expect(tapZoneAction(10, 100, false)).toBe('previous');
    expect(tapZoneAction(50, 100, false)).toBe('toggle-controls');
    expect(tapZoneAction(90, 100, false)).toBe('next');
  });

  it('does not turn a page from a reader control', () => {
    expect(tapZoneAction(10, 100, true)).toBeNull();
  });

  it('maps keyboard page navigation', () => {
    expect(keyboardNavigationAction({ key: 'ArrowLeft', target: null })).toBe('previous');
    expect(keyboardNavigationAction({ key: 'PageDown', target: null })).toBe('next');
    expect(keyboardNavigationAction({ key: 'a', target: null })).toBeNull();
  });
});
