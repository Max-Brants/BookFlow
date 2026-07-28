/**
 * A controller change on an uncontrolled page is the normal first install
 * (`clients.claim()`), not an app update.  Subsequent changes are updates.
 */
export const nextPwaControllerState = (hadController: boolean) => ({
  hadController: true,
  updateReady: hadController,
});
