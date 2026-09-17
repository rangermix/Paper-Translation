import { describe, expect, it } from 'vitest';
import { isLanguageTag, languageCodes, languageName } from './languages';

describe('native language names', () => {
  it('uses each language for its own label and preserves script distinctions', () => {
    expect(['en', 'ja', 'de', 'fr', 'zh-Hans', 'zh-Hant', 'ar'].map(languageName))
      .toEqual(['English', '日本語', 'Deutsch', 'français', '简体中文', '繁體中文', 'العربية']);
    expect(languageName('pt-BR')).toBe('português (Brasil)');
    expect(languageName('unknown-tag')).toBe('unknown-tag');
  });
  it('offers unique language choices and accepts additional tags safely', () => {
    expect(new Set(languageCodes).size).toBe(languageCodes.length);
    for (const code of [...languageCodes, 'ast', 'sr-Latn-RS', 'en-US-u-ca-gregory']) expect(isLanguageTag(code), code).toBe(true);
    for (const code of ['und', 'auto', 'mul', 'zxx', '../en', 'en_US', 'en--US', 'en<script>']) expect(isLanguageTag(code), code).toBe(false);
  });
});
