import { afterEach, expect, it } from 'vitest';
import { setUiLocale, t } from './i18n';
import { ApiError, validatePdfSelection } from './api';
import { UiError, uiMessage } from './ui-message';

afterEach(() => setUiLocale('zh-Hans'));
it('retains parameterized feedback across language changes without interpreting content values', () => {
  setUiLocale('en');
  const error = new UiError('文件超过 {v0} MiB 限制。', { v0: 50 });
  expect(t(error.uiMessage)).toBe('The file exceeds the 50 MiB limit.');
  setUiLocale('zh-Hant');
  expect(t(error.uiMessage)).toBe('檔案超過 50 MiB 限制。');
  const apiError = new ApiError(0, 'INSPECTION_PENDING', uiMessage('原件检查仍在后台处理，可在任务中心查看上传 {v0}。', { v0: '<设置> {v0}' }));
  expect(t(apiError.uiMessage!)).toContain('<设置> {v0}');
  setUiLocale('en');
  expect(t(apiError.uiMessage!)).toContain('<设置> {v0}');
  expect(apiError.message).toBe('原件检查仍在后台处理，可在任务中心查看上传 <设置> {v0}。');
});
it('PDF selection stores message identity and values instead of the current translation', () => {
  const [row] = validatePdfSelection([new File(['%PDF'], 'large.pdf')], 1, 2);
  expect(row.error).toBeInstanceOf(UiError);
  setUiLocale('en'); expect(t(row.error!.uiMessage)).toBe('The file exceeds the 0 MiB limit.');
  setUiLocale('zh-Hans'); expect(t(row.error!.uiMessage)).toBe('文件超过 0 MiB 限制。');
});
