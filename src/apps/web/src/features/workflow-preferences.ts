import { useState } from 'react';
import { useResource } from '../hooks';
import type { Preferences } from '../types';

export function useWorkflowPreferences() {
  const preferences = useResource<Preferences>('/settings/preferences');
  const [localeChoice, setLocale] = useState<string>();
  return {
    preferences,
    ready: Boolean(preferences.data && !preferences.error),
    locale: localeChoice ?? preferences.data?.locale ?? 'zh-Hans',
    policy: 'auto_publish' as const,
    setLocale,
  };
}
