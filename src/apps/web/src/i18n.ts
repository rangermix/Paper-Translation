import { useSyncExternalStore } from 'react';
import { coreMessages } from './locales/core';
import { settingsMessages } from './locales/settings';
import { workflowMessages } from './locales/workflow';
import { editorMessages } from './locales/editor';

export type UiLocale = 'zh-Hans' | 'zh-Hant' | 'en';
export const uiLocaleStorageKey = 'paper-translation.ui-locale.v1';
export const uiLocales: ReadonlyArray<{ value: UiLocale; label: string }> = [
  { value: 'zh-Hans', label: '简体中文' },
  { value: 'zh-Hant', label: '繁體中文' },
  { value: 'en', label: 'English' },
];
export const messages: Record<string, readonly [string, string]> = {
  ...settingsMessages, ...workflowMessages, ...editorMessages, ...coreMessages,
};

export function resolveUiLocale(languages: readonly string[]): UiLocale {
  for (const language of languages) {
    try {
      const locale = new Intl.Locale(language);
      if (locale.language === 'en') return 'en';
      if (locale.language === 'zh') return locale.maximize().script === 'Hant' ? 'zh-Hant' : 'zh-Hans';
    } catch { /* Ignore malformed browser or stored locale tags. */ }
  }
  return 'en';
}
function savedLocale(value: string | null): UiLocale | undefined {
  return uiLocales.find(locale => locale.value === value)?.value;
}
function browserLocale(): UiLocale {
  return typeof window === 'undefined' ? 'zh-Hans' : resolveUiLocale(navigator.languages?.length ? navigator.languages : [navigator.language]);
}
function initialLocale(): UiLocale {
  try { return savedLocale(localStorage.getItem(uiLocaleStorageKey)) ?? browserLocale(); }
  catch { return browserLocale(); }
}
let currentLocale = initialLocale();
const listeners = new Set<() => void>();
export function getUiLocale(): UiLocale { return currentLocale; }
function publishLocale(locale: UiLocale) {
  if (locale === currentLocale) return;
  currentLocale = locale;
  listeners.forEach(listener => listener());
}
export function setUiLocale(locale: UiLocale) {
  if (!uiLocales.some(option => option.value === locale)) return;
  try { localStorage.setItem(uiLocaleStorageKey, locale); } catch { /* The in-memory choice still works when storage is blocked. */ }
  publishLocale(locale);
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export function useUiLocale() { return useSyncExternalStore(subscribe, getUiLocale, () => 'zh-Hans' as const); }
if (typeof window !== 'undefined') {
  window.addEventListener('storage', event => {
    if (event.key !== uiLocaleStorageKey && event.key !== null) return;
    // Only localStorage events affect this browser preference; sessionStorage does not.
    try { if (event.storageArea && event.storageArea !== localStorage) return; } catch { return; }
    publishLocale(savedLocale(event.newValue) ?? browserLocale());
  });
}

/** Translate only application-authored UI messages. Never pass paper/user content. */
export function t(source: string, values?: Record<string, string | number>): string {
  const entry = messages[source];
  const translated = currentLocale === 'zh-Hans' ? source : entry?.[currentLocale === 'en' ? 0 : 1] ?? source;
  return values ? translated.replace(/\{([\w]+)\}/g, (match, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match) : translated;
}
