import { t, formatList } from './i18n';
type Difference = { value: string; unit: string; count: number };
function differences(value: unknown): value is Difference[] {
  return Array.isArray(value) && value.every(v => v && typeof v === 'object'
    && typeof v.value === 'string' && typeof v.unit === 'string' && typeof v.count === 'number');
}
export function NumberEvidence({ evidence }: { evidence: unknown }) {
  if (!evidence || typeof evidence !== 'object') return null;
  const data = evidence as Record<string, unknown>;
  const missing = data.missing_from_target, extra = data.extra_in_target;
  if (!differences(missing) || !differences(extra)) return null;
  const describe = (values: Difference[]) => formatList(values.map(v => t("{value1}{value2}（{value3} 次）", { value1: v.value, value2: v.unit, value3: v.count }))) || t("无");
  return <div className="field-note numeric-difference">
    <strong>{t("数字差异")}</strong>
    <p>{t("译文缺少：{value1}", { value1: String((describe(missing)) ?? '') })}</p><p>{t("译文多出：{value1}", { value1: String((describe(extra)) ?? '') })}</p>
  </div>;
}
