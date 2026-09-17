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
  const describe = (values: Difference[]) => values.map(v => `${v.value}${v.unit}（${v.count} 次）`).join('、') || '无';
  return <div className="field-note numeric-difference">
    <strong>数字差异（已统一小数、千分位和中英文数量单位）</strong>
    <p>译文缺少：{describe(missing)}</p><p>译文多出：{describe(extra)}</p>
  </div>;
}
