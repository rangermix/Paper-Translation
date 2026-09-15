import type { ProviderProtocol } from '../types';

export const providerProtocols: Record<ProviderProtocol, {
  label: string; provider: 'openai' | 'gemini' | 'anthropic' | 'local'; auth: 'bearer' | 'api_key' | 'none'; keyLabel: string; defaultEndpoint: string; defaultModel: string;
}> = {
  local_translation: { label: '本地翻译模型（MLX）', provider: 'local', auth: 'none', keyLabel: '无需密钥', defaultEndpoint: 'http://local-translator:8090/v1/completions', defaultModel: '' },
  responses: { label: 'Responses（OpenAI 兼容）', provider: 'openai', auth: 'bearer', keyLabel: 'Bearer', defaultEndpoint: 'https://api.openai.com/v1/responses', defaultModel: 'gpt-5.4-mini' },
  chat_completions: { label: 'Chat Completions（OpenAI 兼容）', provider: 'openai', auth: 'bearer', keyLabel: 'Bearer', defaultEndpoint: 'https://api.openai.com/v1/chat/completions', defaultModel: 'gpt-5.4-mini' },
  gemini_interactions: { label: 'Gemini Interactions（原生）', provider: 'gemini', auth: 'api_key', keyLabel: 'x-goog-api-key', defaultEndpoint: 'https://generativelanguage.googleapis.com/v1beta/interactions', defaultModel: 'gemini-3.8-flash' },
  claude_messages: { label: 'Claude Messages（原生）', provider: 'anthropic', auth: 'api_key', keyLabel: 'x-api-key', defaultEndpoint: 'https://api.anthropic.com/v1/messages', defaultModel: 'claude-sonnet-5' },
};
