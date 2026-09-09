import { useId, useState } from 'react';
import { languageCodes, languageName, languageTagPattern } from '../languages';

type Props = { id?: string; label?: string; value: string; onChange: (value: string) => void; disabled?: boolean; emptyLabel?: string };

export function LanguageSelect({ id, label, value, onChange, disabled, emptyLabel }: Props) {
  const generatedId = useId();
  const selectId = id ?? generatedId;
  const [custom, setCustom] = useState(false);
  const options = value && !languageCodes.includes(value) && !custom ? [...languageCodes, value] : languageCodes;
  return <>
    <select id={selectId} aria-label={label} value={custom ? '__custom' : value} disabled={disabled} required={!emptyLabel}
      onChange={event => {
        const next = event.target.value;
        setCustom(next === '__custom');
        onChange(next === '__custom' ? '' : next);
      }}>
      {(emptyLabel || !value && !custom) && <option value="">{emptyLabel ?? '请选择语言'}</option>}
      {options.map(locale => <option key={locale} value={locale} lang={locale}>{languageName(locale)}</option>)}
      <option value="__custom">其他语言…</option>
    </select>
    {custom && <label className="field" htmlFor={`${selectId}-code`}>语言代码（如 fil、pt-BR）
      <input className="input" id={`${selectId}-code`} value={value} required disabled={disabled} maxLength={32}
        pattern={languageTagPattern} autoCapitalize="none" spellCheck={false} onChange={event => onChange(event.target.value.trim())}/>
      {value && <small lang={value}>{languageName(value)}</small>}
    </label>}
  </>;
}
