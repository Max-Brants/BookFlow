interface AuthenticationState {
  authChecked: boolean;
  authRequired: boolean;
  isAuthenticated: boolean;
}

export const shouldEnableAuthenticatedServices = ({
  authChecked,
  authRequired,
  isAuthenticated,
}: AuthenticationState): boolean => authChecked && (!authRequired || isAuthenticated);
