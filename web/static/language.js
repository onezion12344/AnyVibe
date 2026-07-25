/* Shared, dependency-free bilingual UI controller for Coding Vibe pages. */
(() => {
  const STORAGE_KEY = 'coding-vibe-language';
  const supported = new Set(['en', 'zh']);

  function preferredLanguage() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (supported.has(saved)) return saved;
    } catch {}
    return (navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en';
  }

  function dictionary() {
    return window.CV_I18N || {};
  }

  function translate(key, fallback = '') {
    const entry = dictionary()[key];
    if (!entry) return fallback || key;
    return entry[window.cvLanguage] || entry.en || entry.zh || fallback || key;
  }

  function applyLanguage(language) {
    window.cvLanguage = supported.has(language) ? language : 'en';
    document.documentElement.lang = window.cvLanguage === 'zh' ? 'zh-CN' : 'en';
    document.querySelectorAll('[data-i18n]').forEach(element => {
      element.textContent = translate(element.dataset.i18n, element.textContent);
    });
    document.querySelectorAll('[data-i18n-aria-label]').forEach(element => {
      element.setAttribute('aria-label', translate(element.dataset.i18nAriaLabel, element.getAttribute('aria-label') || ''));
    });
    document.querySelectorAll('[data-language-toggle]').forEach(button => {
      const next = window.cvLanguage === 'zh' ? 'en' : 'zh';
      button.textContent = next === 'zh' ? '中文' : 'EN';
      button.setAttribute('aria-label', translate(next === 'zh' ? 'switch_to_chinese' : 'switch_to_english'));
      button.title = button.getAttribute('aria-label');
    });
    try { localStorage.setItem(STORAGE_KEY, window.cvLanguage); } catch {}
    window.dispatchEvent(new CustomEvent('cv-language-change', { detail: { language: window.cvLanguage } }));
  }

  window.cvT = translate;
  window.cvSetLanguage = applyLanguage;

  document.addEventListener('DOMContentLoaded', () => {
    applyLanguage(preferredLanguage());
    document.querySelectorAll('[data-language-toggle]').forEach(button => {
      button.addEventListener('click', () => applyLanguage(window.cvLanguage === 'zh' ? 'en' : 'zh'));
    });
  });
})();
