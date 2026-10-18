import { describe, expect, it } from 'vitest';
import { isLanguageTag, languageCodes, languageName, localizedLanguageName, matchesLanguage, parseRecentLanguages, rememberLanguage } from './languages';

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

describe('searchable language choices', () => {
  it('finds localized, native, accented and locale names without merging scripts or regions', () => {
    expect(matchesLanguage('ja', '日语')).toBe(true);
    expect(matchesLanguage('de', 'Deutsch')).toBe(true);
    expect(matchesLanguage('fr', 'francais')).toBe(true);
    expect(matchesLanguage('zh-Hans', '中文')).toBe(true);
    expect(matchesLanguage('zh-Hant', '中文')).toBe(true);
    expect(matchesLanguage('zh-Hans', 'zh-Hant')).toBe(false);
    expect(matchesLanguage('zh-Hant', 'zh-Hant')).toBe(true);
    expect(matchesLanguage('pt-BR', 'pt-br')).toBe(true);
    expect(matchesLanguage('pt', 'pt-br')).toBe(false);
    expect(matchesLanguage('sr-Latn-RS', 'sr-latn-rs')).toBe(true);
    expect(matchesLanguage('en', '不存在的语言')).toBe(false);
    expect(localizedLanguageName('unknown_tag')).toBe('unknown_tag');
  });
  it('stores only bounded valid language identifiers and keeps exact variants', () => {
    expect(parseRecentLanguages('malformed')).toEqual([]);
    expect(parseRecentLanguages(JSON.stringify({ key: 'secret' }))).toEqual([]);
    expect(parseRecentLanguages(JSON.stringify(['zh-Hans', 'zh-Hant', 'zh-Hans', 1, 'en_US', 'auto', '../fr', 'pt-BR'])))
      .toEqual(['zh-Hans', 'zh-Hant', 'pt-BR']);
    expect(rememberLanguage('zh-Hant', ['zh-Hans', 'pt-BR', 'zh-Hant'])).toEqual(['zh-Hant', 'zh-Hans', 'pt-BR']);
    expect(rememberLanguage('', ['zh-Hans'])).toEqual(['zh-Hans']);
    expect(rememberLanguage('ast', ['en', 'fr', 'de', 'ja', 'ko', 'ar'])).toHaveLength(6);
  });
});
