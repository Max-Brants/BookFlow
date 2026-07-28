// Apply theme immediately before first paint to prevent flash.
// This runs as a blocking script before the app bundle loads.
(function () {
  var saved = localStorage.getItem('bookflow-theme');
  if (!saved) {
    var legacy = localStorage.getItem('preferred-theme');
    saved = legacy === 'light' || legacy === 'dark' ? legacy : 'dark';
  }
  var theme =
    saved === 'auto'
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
      : saved;

  var dark = theme === 'dark';
  var bg = dark ? '#0b0f19' : '#f6f7fb';
  var fg = dark ? '#e8ecf5' : '#172033';

  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.style.colorScheme = theme;

  var s = document.createElement('style');
  s.id = 'theme-init';
  s.textContent = 'html,body,#root{background:' + bg + ';color:' + fg + '}';
  document.head.appendChild(s);

  document.documentElement.classList.add('preload');
})();
