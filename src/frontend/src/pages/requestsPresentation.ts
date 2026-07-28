const terminalRequestProcessStatuses = new Set(['completed', 'cancelled', 'failed']);

export const canManageRequestProcess = (
  history: boolean,
  status: string | null | undefined,
): boolean => !history && Boolean(status) && !terminalRequestProcessStatuses.has(status ?? '');
