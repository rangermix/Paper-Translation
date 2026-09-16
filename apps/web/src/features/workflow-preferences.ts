import { useState } from 'react';
import { useResource } from '../hooks';
import type { Preferences } from '../types';

export function useWorkflowPreferences() {
  const preferences = useResource<Preferences>('/settings/preferences');
  const [localeChoice, setLocale] = useState<string>();
  const [policyChoice, setPolicy] = useState<Preferences['publish_policy']>();
  return {
    preferences,
    ready: Boolean(preferences.data && !preferences.error),
    locale: localeChoice ?? preferences.data?.locale ?? 'zh-Hans',
    policy: policyChoice ?? preferences.data?.publish_policy ?? 'auto_publish',
    setLocale,
    setPolicy,
  };
}
