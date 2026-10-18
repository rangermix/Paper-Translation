/** Keep authored feedback and its data separate until the UI renders it. */
export type UiMessage = { key: string; values?: Record<string, string | number> };
export type UiText = string | UiMessage;
export function uiMessage(key: string, values?: UiMessage['values']): UiMessage { return { key, values }; }
export function messageSource(message: UiText): string {
  return typeof message === 'string' ? message : message.key.replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.prototype.hasOwnProperty.call(message.values ?? {}, name) ? String(message.values![name]) : match);
}
export class UiError extends Error {
  readonly uiMessage: UiMessage;
  constructor(key: string, values?: UiMessage['values']) {
    const message = uiMessage(key, values);
    super(messageSource(message));
    this.uiMessage = message;
  }
}
