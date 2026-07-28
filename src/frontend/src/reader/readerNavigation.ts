export type ReaderNavigationAction = 'previous' | 'next' | 'toggle-controls' | null;

/**
 * Resolve tap zones without acting during selection or gestures. The middle half
 * intentionally leaves enough room for links and reader controls.
 */
export const tapZoneAction = (
  clientX: number,
  viewportWidth: number,
  isInteractive: boolean,
): ReaderNavigationAction => {
  if (isInteractive || viewportWidth <= 0) return null;
  const ratio = clientX / viewportWidth;
  if (ratio < 0.25) return 'previous';
  if (ratio > 0.75) return 'next';
  return 'toggle-controls';
};

export const keyboardNavigationAction = (
  event: Pick<KeyboardEvent, 'key' | 'target'>,
): 'previous' | 'next' | null => {
  const target = event.target;
  if (
    typeof HTMLElement !== 'undefined' &&
    target instanceof HTMLElement &&
    (target.isContentEditable || ['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(target.tagName))
  ) {
    return null;
  }
  if (['ArrowLeft', 'PageUp'].includes(event.key)) return 'previous';
  if (['ArrowRight', 'PageDown', ' '].includes(event.key)) return 'next';
  return null;
};
