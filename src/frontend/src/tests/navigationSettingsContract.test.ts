import { readFile } from 'node:fs/promises';

import { describe, expect, it } from 'vitest';

const sourceRoot = new URL('..', import.meta.url);
const readSource = (relativePath: string) => readFile(new URL(relativePath, sourceRoot), 'utf8');

describe('navigation and personal-settings contracts', () => {
  it('uses standalone Requests and admin-only Downloads pages, without the old request-process entry', async () => {
    const [navigation, translations] = await Promise.all([
      readSource('library/LibraryNavigation.tsx'),
      readSource('i18n/translations.ts'),
    ]);

    expect(navigation).toContain('to="/requests"');
    expect(navigation).toContain('to="/admin/downloads"');
    expect(navigation).not.toContain('onDownloadsClick');
    expect(navigation).not.toContain('/admin/request-processes');
    expect(navigation).not.toContain('/admin/operations');
    expect(navigation).not.toMatch(/tagline/i);
    expect(translations).toContain("'nav.downloads': 'Downloads'");
    expect(translations).not.toMatch(/brand\.tagline|Jouw boeken, altijd in beweging/i);
  });

  it('uses routes instead of an activity sidebar and removes the legacy book-library URL', async () => {
    const [app, header] = await Promise.all([
      readSource('App.tsx'),
      readSource('components/Header.tsx'),
    ]);
    expect(app).toContain('path="/requests"');
    expect(app).toContain('path="/admin/downloads"');
    expect(app).not.toContain('<ActivitySidebar');
    expect(app).not.toContain('calibreWebUrl');
    expect(header).not.toContain('calibreWebUrl');
  });

  it('defines interactive Account, Personal notifications, and Kobo tabs, with theme only in Account', async () => {
    const source = await readSource('pages/SelfSettingsPage.tsx');

    expect(source).toContain("useState<'account' | 'notifications' | 'kobo'>('account')");
    expect(source).toMatch(
      /\['account', t\('settings\.account'\)\][\s\S]*?\['notifications', t\('settings\.notifications'\)\][\s\S]*?\['kobo', 'Kobo'\]/,
    );
    expect(source).toContain('onClick={() => setActiveTab(tab)}');
    expect(source).toContain("{activeTab === 'account' && (");
    expect(source).toContain("{activeTab === 'notifications' && (");
    expect(source).toContain("{activeTab === 'kobo' && (");

    const accountSection = source.slice(
      source.indexOf("{activeTab === 'account' && ("),
      source.indexOf("{activeTab === 'notifications' && ("),
    );
    const notificationsSection = source.slice(
      source.indexOf("{activeTab === 'notifications' && ("),
      source.indexOf("{activeTab === 'kobo' && ("),
    );
    expect(accountSection).toContain('setThemePreference(value)');
    expect(notificationsSection).not.toContain('setThemePreference(value)');
  });

  it('keeps Kobo and library as separate routes and folds system operations into admin settings', async () => {
    const [app, settingsModal] = await Promise.all([
      readSource('App.tsx'),
      readSource('components/settings/SettingsModal.tsx'),
    ]);

    expect(app).toContain('path="/library" element={<LibraryPage koboEnabled={koboEnabled} />}');
    expect(app).toContain(
      'path="/kobo" element={<LibraryPage koboEnabled={koboEnabled} koboOnly />}',
    );
    expect(app).toContain('to="/admin/settings?tab=system-operations"');
    expect(settingsModal).toContain("name: 'system_operations'");
    expect(settingsModal).toContain('<AdminOperationsPage embedded />');
    expect(settingsModal).toContain("requestedTab === 'system-operations'");
  });

  it('keeps contextual book details in their owning navigation sections', async () => {
    const [app, navigation, discover, suggestions, library, dashboard] = await Promise.all([
      readSource('App.tsx'),
      readSource('library/LibraryNavigation.tsx'),
      readSource('components/DiscoverNavigation.tsx'),
      readSource('pages/SuggestionsPage.tsx'),
      readSource('library/LibraryPage.tsx'),
      readSource('pages/DashboardPage.tsx'),
    ]);

    expect(app).toContain('path="/library/:bookId"');
    expect(app).toContain('path="/kobo/:bookId"');
    expect(app).toContain('path="/suggestions/:listKey/:bookId"');
    expect(app).not.toContain('LegacyLibraryBookRedirect');

    const catalogPosition = navigation.indexOf('to="/catalog"');
    const trendingPosition = navigation.indexOf('to="/suggestions/overall"');
    const followingPosition = navigation.indexOf('to="/monitors"');
    expect(catalogPosition).toBeGreaterThan(-1);
    expect(trendingPosition).toBeGreaterThan(catalogPosition);
    expect(followingPosition).toBeGreaterThan(trendingPosition);
    expect(navigation).toContain("location.pathname.startsWith('/suggestions/')");

    expect(discover).not.toContain('/suggestions/overall');
    expect(suggestions).not.toContain('<DiscoverNavigation');
    expect(suggestions).toContain("contextualBookPath('trending'");
    expect(library).toMatch(/koboOnly \? `\/kobo\/\$\{book\.id\}` : `\/library\/\$\{book\.id\}`/);
    expect(dashboard).toMatch(/to=\{`\/suggestions\/overall\/\$\{book\.id\}`\}/);
  });
});
