import { getUiLocale, t } from '../i18n';
import { useEffect, useId, useRef, useState } from 'react';
import { isLanguageTag, languageCodes, languageName, languageTagPattern, localizedLanguageName, matchesLanguage, parseRecentLanguages, recentLanguagesKey, rememberLanguage } from '../languages';
import './language-select.css';

type Props = { id?: string; label?: string; value: string; onChange: (value: string) => void; disabled?: boolean; emptyLabel?: string };
const loadRecent = () => { try { return parseRecentLanguages(localStorage.getItem(recentLanguagesKey)); } catch { return []; } };

export function LanguageSelect({ id, label, value, onChange, disabled, emptyLabel }: Props) {
  const generatedId = useId();
  const selectId = id ?? generatedId;
  const [custom, setCustom] = useState(false);
  const [recent, setRecent] = useState(loadRecent);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [fieldName, setFieldName] = useState(label ?? '语言');
  const uiLocale = getUiLocale();
  const select = useRef<HTMLSelectElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const activeOption = useRef<HTMLButtonElement>(null);
  const options = [...new Set([...recent, ...languageCodes, ...(value && !custom ? [value] : [])])];
  const matches = open ? options.filter(locale => matchesLanguage(locale, query)) : [];
  const currentActive = Math.min(active, Math.max(0, matches.length - 1));
  const recentOptions = options.filter(locale => recent.includes(locale));
  const otherOptions = options.filter(locale => !recent.includes(locale));

  function remember(locale: string) {
    const next = rememberLanguage(locale, loadRecent());
    setRecent(next);
    try { localStorage.setItem(recentLanguagesKey, JSON.stringify(next)); } catch { /* Selection also works when browser storage is unavailable. */ }
  }
  function choose(locale: string) {
    setCustom(false); onChange(locale); remember(locale); setOpen(false); trigger.current?.focus();
  }
  function close() { setOpen(false); trigger.current?.focus(); }
  useEffect(() => { setFieldName(label ?? select.current?.labels?.[0]?.textContent?.trim() ?? '语言'); }, [label, uiLocale]);
  useEffect(() => { if (open) search.current?.focus(); }, [open]);
  useEffect(() => { if (open) activeOption.current?.scrollIntoView({ block: 'nearest' }); }, [currentActive, open, query]);

  return <div className="language-picker" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
    <div className="language-picker-control">
      <select ref={select} id={selectId} aria-label={label} value={custom ? '__custom' : value} disabled={disabled} required={!emptyLabel}
        onFocus={() => setRecent(loadRecent())} onChange={event => {
          const next = event.target.value;
          setCustom(next === '__custom'); onChange(next === '__custom' ? '' : next);
          if (next !== '__custom' && next) remember(next);
        }}>
        {(emptyLabel || !value && !custom) && <option value="">{emptyLabel ?? t("请选择语言")}</option>}
        {!!recentOptions.length && <optgroup label={t("最近使用")}>{recentOptions.map(locale => <option key={locale} value={locale} lang={locale}>{languageName(locale)}</option>)}</optgroup>}
        <optgroup label={t("全部语言")}>{otherOptions.map(locale => <option key={locale} value={locale} lang={locale}>{languageName(locale)}</option>)}</optgroup>
        <option value="__custom">{t("其他语言…")}</option>
      </select>
      <button ref={trigger} type="button" className="btn language-search-trigger" disabled={disabled} aria-expanded={open} aria-controls={`${selectId}-search-panel`}
        onClick={() => { setFieldName(label ?? select.current?.labels?.[0]?.textContent?.trim() ?? '语言'); setRecent(loadRecent()); setQuery(''); setActive(0); setOpen(previous => !previous); }}>{t("查找语言")}</button>
    </div>
    {value && !custom && <small className="language-current">{t("当前：")}<span lang={value}>{languageName(value)}</span>{languageName(value) !== value && <> · <span>{value}</span></>}</small>}
    {open && !disabled && <div id={`${selectId}-search-panel`} className="language-search-panel" role="region" aria-label={t("{field}：查找语言", { field: t(label ?? fieldName) })}>
      <label htmlFor={`${selectId}-search`}>{t("搜索语言名称或代码")}</label>
      <div className="language-search-input"><input ref={search} id={`${selectId}-search`} className="input" role="combobox" aria-autocomplete="list" aria-expanded="true" aria-controls={`${selectId}-matches`}
        aria-activedescendant={matches.length ? `${selectId}-match-${currentActive}` : undefined} autoComplete="off" spellCheck={false} value={query} placeholder={t("如 中文、Deutsch、pt-BR")}
        onChange={event => { setQuery(event.target.value); setActive(0); }} onKeyDown={event => {
          if (event.nativeEvent.isComposing) return;
          if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
          else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setActive(previous => Math.max(0, Math.min(matches.length - 1, previous + (event.key === 'ArrowDown' ? 1 : -1)))); }
          else if (event.key === 'Enter') { event.preventDefault(); if (matches[currentActive]) choose(matches[currentActive]); }
        }}/><button className="btn sm" type="button" onClick={close}>{t("关闭")}</button></div>
      <p role="status" className="small muted language-match-count">{matches.length ? (query ? t("{count} 种语言匹配", { count: matches.length }) : t("{count} 种语言，最近使用排在前面", { count: matches.length })) : t("没有匹配语言。可更换关键词，或选择“其他语言…”输入代码。")}</p>
      <div id={`${selectId}-matches`} role="listbox" aria-label={t("{field}搜索结果", { field: t(label ?? fieldName) })} className="language-matches">
        {matches.map((locale, index) => <button key={locale} id={`${selectId}-match-${index}`} ref={index === currentActive ? activeOption : undefined} type="button" role="option" aria-selected={index === currentActive}
          tabIndex={-1} className="language-match" onMouseDown={event => event.preventDefault()} onClick={() => choose(locale)}>
          <span><strong lang={locale}>{languageName(locale)}</strong>{localizedLanguageName(locale) !== languageName(locale) && <span className="language-localized">{localizedLanguageName(locale)}</span>}</span>
          <span className="language-match-code">{languageName(locale) !== locale && locale}{recent.includes(locale) && <small>{t("最近使用")}</small>}{locale === value && <small>{t("当前")}</small>}</span>
        </button>)}
      </div>
    </div>}
    {custom && <label className="field language-custom" htmlFor={`${selectId}-code`}>{t("语言代码（如 fil、pt-BR）")}<input className="input" id={`${selectId}-code`} value={value} required disabled={disabled} maxLength={32}
        pattern={languageTagPattern} autoCapitalize="none" spellCheck={false} onBlur={() => { if (isLanguageTag(value)) remember(value); }} onChange={event => onChange(event.target.value.trim())}/>
      {value && <small lang={value}>{languageName(value)}</small>}
    </label>}
  </div>;
}
