import type { Provider } from '../types';

// A missing flag belongs to a legacy profile and preserves its existing controls.
export const costControlEnabled = (profile?: Pick<Provider, 'cost_control_enabled'>) => profile?.cost_control_enabled !== false;
export const defaultTokenLimits = { max_input_tokens: 32768, max_output_tokens: 8192, max_unit_characters: 2000 };
export const budgetValid = (value: string) => {
  const micro = Math.round(Number(value) * 1_000_000);
  return Number.isSafeInteger(micro) && micro > 0;
};
export function CostControlNotice({ enabled }: { enabled: boolean }) {
  return enabled ? null : <p className="notice">未启用预算与成本控制：本任务不设金额上限，服务仍可能收费。无法计算的费用显示为“未计算”，不是 0。</p>;
}
