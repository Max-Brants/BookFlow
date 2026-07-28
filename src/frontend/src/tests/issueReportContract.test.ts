import { readFile } from 'node:fs/promises';

import { describe, expect, it } from 'vitest';

const sourceRoot = new URL('..', import.meta.url);
const readSource = (relativePath: string) => readFile(new URL(relativePath, sourceRoot), 'utf8');

describe('in-app issue reporting contract', () => {
  it('replaces external navigation with a configured authenticated modal action', async () => {
    const [header, app] = await Promise.all([
      readSource('components/Header.tsx'),
      readSource('App.tsx'),
    ]);

    expect(header).toContain('issueReportingEnabled && isAuthenticated');
    expect(header).toContain('<IssueReportModal');
    expect(header).not.toContain('calibrain/bookflow/issues');
    expect(app).toContain('config?.issue_reporting_enabled === true');
  });

  it('supports URL prefill, bounded fields, choosing, dropping and pasting one image', async () => {
    const modal = await readSource('components/IssueReportModal.tsx');

    expect(modal).toContain('setPageUrl(window.location.href)');
    expect(modal).toContain('maxLength={200}');
    expect(modal).toContain('maxLength={10000}');
    expect(modal).toContain('MAX_IMAGE_BYTES');
    expect(modal).toContain('accept="image/png,image/jpeg,image/webp"');
    expect(modal).toContain('onDrop={handleDrop}');
    expect(modal).toContain('onPaste={handlePaste}');
    expect(modal).toContain('URL.createObjectURL(image)');
    expect(modal).toContain('useEscapeKey(isOpen && !isSubmitting');
  });

  it('keeps credentials in-app and submits multipart data with CSRF and idempotency', async () => {
    const client = await readSource('services/v1Api.ts');

    expect(client).toContain('/issue-reports');
    expect(client).toContain("'X-BookFlow-CSRF': '1'");
    expect(client).toContain("'Idempotency-Key': idempotencyKey");
    expect(client).toContain('body: data');
    expect(client).not.toContain('GITHUB_ISSUE_TOKEN');
  });
});
