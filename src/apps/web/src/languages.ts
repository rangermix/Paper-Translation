// A broad picker, not an allowlist. Other language/script/region tags can be entered too.
export const languageCodes = `zh-Hans zh-Hant en ja de fr es pt pt-BR it ko ar ru
aa ab ae af ak am an as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu cv cy
da dv dz ee el eo et eu fa ff fi fj fo fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz
ia id ie ig ii ik io is iu jv ka kg ki kj kk kl km kn kr ks ku kv kw ky la lb lg li ln lo lt lu lv
mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps
qu rm rn ro rw sa sc sd se sg sh si sk sl sm sn so sq sr sr-Latn ss st su sv sw ta te tg th ti tk
tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu fil yue`.split(/\s+/);

const nativeNames: Record<string, string> = {
  // Frozen native names also work in browsers with reduced ICU locale data.
  'fr': "français",
  'es': "español",
  'pt': "português",
  'pt-BR': "português (Brasil)",
  'it': "italiano",
  'ko': "한국어",
  'ar': "العربية",
  'ru': "русский",
  'af': "Afrikaans",
  'ak': "Akan",
  'am': "አማርኛ",
  'as': "অসমীয়া",
  'az': "azərbaycan",
  'be': "беларуская",
  'bg': "български",
  'bm': "bamanakan",
  'bn': "বাংলা",
  'bo': "བོད་སྐད་",
  'br': "brezhoneg",
  'bs': "bosanski",
  'ca': "català",
  'ce': "нохчийн",
  'cs': "čeština",
  'cy': "Cymraeg",
  'da': "dansk",
  'dz': "རྫོང་ཁ",
  'ee': "eʋegbe",
  'el': "Ελληνικά",
  'eo': "Esperanto",
  'et': "eesti",
  'eu': "euskara",
  'fa': "فارسی",
  'ff': "Pulaar",
  'fi': "suomi",
  'fo': "føroyskt",
  'fy': "Frysk",
  'ga': "Gaeilge",
  'gd': "Gàidhlig",
  'gl': "galego",
  'gu': "ગુજરાતી",
  'gv': "Gaelg",
  'ha': "Hausa",
  'he': "עברית",
  'hi': "हिन्दी",
  'hr': "hrvatski",
  'hu': "magyar",
  'hy': "հայերեն",
  'ia': "interlingua",
  'id': "Indonesia",
  'ig': "Igbo",
  'ii': "ꆈꌠꉙ",
  'is': "íslenska",
  'jv': "Jawa",
  'ka': "ქართული",
  'ki': "Gikuyu",
  'kk': "қазақ тілі",
  'kl': "kalaallisut",
  'km': "ខ្មែរ",
  'kn': "ಕನ್ನಡ",
  'ks': "کٲشُر",
  'ku': "kurdî (kurmancî)",
  'kw': "kernewek",
  'ky': "кыргызча",
  'lb': "Lëtzebuergesch",
  'lg': "Luganda",
  'ln': "lingála",
  'lo': "ລາວ",
  'lt': "lietuvių",
  'lv': "latviešu",
  'mg': "Malagasy",
  'mi': "Māori",
  'mk': "македонски",
  'ml': "മലയാളം",
  'mn': "монгол",
  'mr': "मराठी",
  'ms': "Melayu",
  'mt': "Malti",
  'my': "မြန်မာ",
  'nb': "norsk bokmål",
  'nd': "isiNdebele",
  'ne': "नेपाली",
  'nl': "Nederlands",
  'nn': "norsk nynorsk",
  'no': "norsk",
  'oc': "occitan",
  'om': "Oromoo",
  'or': "ଓଡ଼ିଆ",
  'os': "ирон",
  'pa': "ਪੰਜਾਬੀ",
  'pl': "polski",
  'ps': "پښتو",
  'qu': "Runasimi",
  'rm': "rumantsch",
  'ro': "română",
  'rw': "Ikinyarwanda",
  'sa': "संस्कृत भाषा",
  'sd': "سنڌي",
  'se': "davvisámegiella",
  'sg': "Sängö",
  'si': "සිංහල",
  'sk': "slovenčina",
  'sl': "slovenščina",
  'sn': "chiShona",
  'so': "Soomaali",
  'sq': "shqip",
  'sr': "српски",
  'sr-Latn': "srpski (latinica)",
  'st': "Sesotho",
  'su': "Basa Sunda",
  'sv': "svenska",
  'sw': "Kiswahili",
  'ta': "தமிழ்",
  'te': "తెలుగు",
  'tg': "тоҷикӣ",
  'th': "ไทย",
  'ti': "ትግርኛ",
  'tk': "türkmen dili",
  'tl': "Filipino",
  'tn': "Setswana",
  'to': "lea fakatonga",
  'tr': "Türkçe",
  'tt': "татар",
  'ug': "ئۇيغۇرچە",
  'uk': "українська",
  'ur': "اردو",
  'uz': "o‘zbek",
  'vi': "Tiếng Việt",
  'wo': "Wolof",
  'xh': "IsiXhosa",
  'yi': "ייִדיש",
  'yo': "Èdè Yorùbá",
  'zu': "isiZulu",
  'fil': "Filipino",
  'yue': "粵語",
  'zh-Hans': '简体中文', 'zh-Hant': '繁體中文', zh: '中文', en: 'English', ja: '日本語', de: 'Deutsch',
  aa: 'Qafar af', ab: 'Аҧсуа', ae: 'Avesta', av: 'Авар мацӀ', ay: 'Aymar aru', ba: 'Башҡорт теле',
  bh: 'भोजपुरी', bi: 'Bislama', ch: 'Chamoru', cr: 'ᓀᐦᐃᔭᐍᐏᐣ', cu: 'Словѣньскъ', cv: 'Чӑвашла',
  fj: 'Vosa Vakaviti', ho: 'Hiri Motu', hz: 'Otjiherero', ie: 'Interlingue', ik: 'Iñupiatun',
  io: 'Ido', kg: 'Kikongo', kj: 'Kuanyama', kr: 'Kanuri', kv: 'Коми кыв', lu: 'Tshiluba',
  mh: 'Kajin M̧ajeļ', na: 'Dorerin Naoero', ng: 'Owambo', nv: 'Diné bizaad', oj: 'ᐊᓂᔑᓈᐯᒧᐎᓐ',
  pi: 'पालि', rn: 'Ikirundi', sc: 'Sardu', sh: 'Srpskohrvatski', sm: 'Gagana Sāmoa',
  ty: 'Reo Tahiti', ve: 'Tshivenḓa', vo: 'Volapük', wa: 'Walon', za: 'Vahcuengh',
  an: 'aragonés', co: 'Corsu', dv: 'ދިވެހި', gn: "Avañe'ẽ", ht: 'Kreyòl ayisyen', iu: 'ᐃᓄᒃᑎᑐᑦ',
  la: 'Latina', li: 'Limburgs', nr: 'isiNdebele', ny: 'Chichewa', ss: 'siSwati', ts: 'itsonga', tw: 'Twi',
};
const nameCache = new Map<string, string>();

export function languageName(locale?: string | null): string {
  if (!locale) return '';
  if (locale === 'und') return '尚未识别';
  if (locale === 'auto') return '自动识别';
  if (nativeNames[locale]) return nativeNames[locale];
  const cached = nameCache.get(locale);
  if (cached) return cached;
  let name = locale;
  try {
    // Do not let an unavailable display locale silently use the interface language.
    if (Intl.DisplayNames.supportedLocalesOf([locale]).length) {
      name = new Intl.DisplayNames([locale], { type: 'language', languageDisplay: 'standard', fallback: 'code' }).of(locale) || locale;
    }
  } catch { /* Preserve unfamiliar historical tags as readable identifiers. */ }
  nameCache.set(locale, name);
  return name;
}

export const languageTagPattern = '(?:[a-zA-Z]{2,3}(?:-[a-zA-Z]{3}){0,3}|[a-zA-Z]{4}|[a-zA-Z]{5,8})(?:-[a-zA-Z]{4})?(?:-(?:[a-zA-Z]{2}|[0-9]{3}))?(?:-(?:[a-zA-Z0-9]{5,8}|[0-9][a-zA-Z0-9]{3}))*(?:-[0-9a-wy-zA-WY-Z](?:-[a-zA-Z0-9]{2,8})+)*(?:-[xX](?:-[a-zA-Z0-9]{1,8})+)?';
const validTag = new RegExp(`^(?:${languageTagPattern})$`);
export function isLanguageTag(value?: string | null): value is string {
  return !!value && value.length <= 32 && validTag.test(value) && !['und', 'auto', 'mul', 'zxx'].includes(value.split('-')[0].toLowerCase());
}
