'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';

interface AppMeta {
  version: string;
  enable_user_api_keys: boolean;
  api_key_restricted_to_emails: boolean;
  enable_api_keys_menu: boolean;
  enable_billing: boolean;
  billing_disabled_message: string | null;
  enable_translation: boolean;
  debug: boolean;
}

interface FeatureFlagScenario {
  name: string;
  config: Record<string, boolean | string>;
  behavior: string;
  useCase: string;
}

const FEATURE_FLAG_SCENARIOS: FeatureFlagScenario[] = [
  {
    name: 'Development/Demo Mode',
    config: {
      'ENABLE_USER_API_KEYS': false,
    },
    behavior: 'System uses its own API keys. No user configuration needed.',
    useCase: 'Demo server, development, testing without real API keys',
  },
  {
    name: 'Open Access - Free Tier',
    config: {
      'ENABLE_USER_API_KEYS': true,
      'API_KEY_ALLOWED_EMAILS': '[]',
    },
    behavior: 'All users must provide their own API key to use the service.',
    useCase: 'SaaS product with free tier that requires user API keys',
  },
  {
    name: 'Selective Access - Allowlisted Users',
    config: {
      'ENABLE_USER_API_KEYS': true,
      'API_KEY_ALLOWED_EMAILS': '["admin@example.com", "team@company.com"]',
    },
    behavior: 'Only allowlisted emails get free access with system API keys. Others must provide their own.',
    useCase: 'Enterprise license where specific users get free access',
  },
  {
    name: 'API Keys Menu Disabled',
    config: {
      'ENABLE_API_KEYS_MENU': false,
    },
    behavior: 'Users cannot see or manage their own API keys in settings.',
    useCase: 'When you want to hide API key management from UI',
  },
  {
    name: 'Billing Enabled',
    config: {
      'ENABLE_BILLING': true,
    },
    behavior: 'Billing features are active. Users see pricing and payment options.',
    useCase: 'Commercial deployment with paid tiers',
  },
  {
    name: 'Billing Disabled with Message',
    config: {
      'ENABLE_BILLING': false,
      'BILLING_DISABLED_MESSAGE': '"Coming soon..."',
    },
    behavior: 'Billing features hidden. Users see a custom message explaining why.',
    useCase: 'Early access or beta where billing is not yet available',
  },
  {
    name: 'Translation Enabled',
    config: {
      'ENABLE_TRANSLATION': true,
    },
    behavior: 'Language selection available in UI. Can generate recaps in multiple languages.',
    useCase: 'Multi-language support for international users',
  },
  {
    name: 'Debug Mode',
    config: {
      'DEBUG': true,
    },
    behavior: 'Additional logging and debugging information displayed.',
    useCase: 'Development and troubleshooting',
  },
];

export default function FeatureFlagsPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [meta, setMeta] = useState<AppMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading) return;
    if (!user?.is_admin) {
      router.push('/dashboard');
      return;
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    const fetchMeta = async () => {
      try {
        const response = await fetch('/api/v1/meta');
        if (!response.ok) throw new Error(`Failed to fetch app metadata: ${response.status}`);
        const data = await response.json();
        setMeta(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchMeta();
  }, []);

  if (authLoading || loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-lg text-gray-500">Loading feature flags...</p>
      </div>
    );
  }

  if (!user?.is_admin) {
    return null;
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-lg text-red-600">Error: {error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 p-6 max-w-6xl">
      {/* Header */}
      <div>
        <h1 className="text-4xl font-bold mb-2">Feature Flags</h1>
        <p className="text-gray-600">Overview of all feature flags and their combinations</p>
      </div>

      {/* Current Configuration */}
      <div className="bg-white dark:bg-gray-950 rounded-lg border border-gray-200 dark:border-gray-800 p-6">
        <h2 className="text-2xl font-bold mb-6">Current Configuration</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          {/* API Key Features */}
          <div>
            <h3 className="font-bold text-lg mb-4 text-gray-900 dark:text-white">API Key Features</h3>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-gray-600 dark:text-gray-400">User API Keys Enabled:</span>
                <span className={meta?.enable_user_api_keys ? 'text-green-600 font-bold' : 'text-red-600 font-bold'}>
                  {meta?.enable_user_api_keys ? '✓ Yes' : '✗ No'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-600 dark:text-gray-400">API Keys Restricted:</span>
                <span className={meta?.api_key_restricted_to_emails ? 'text-orange-600 font-bold' : 'text-blue-600 font-bold'}>
                  {meta?.api_key_restricted_to_emails ? '✓ Yes (Allowlist)' : '✗ No (All users)'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-600 dark:text-gray-400">API Keys Menu:</span>
                <span className={meta?.enable_api_keys_menu ? 'text-green-600 font-bold' : 'text-red-600 font-bold'}>
                  {meta?.enable_api_keys_menu ? '✓ Visible' : '✗ Hidden'}
                </span>
              </div>
            </div>
          </div>

          {/* Other Features */}
          <div>
            <h3 className="font-bold text-lg mb-4 text-gray-900 dark:text-white">Other Features</h3>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-gray-600 dark:text-gray-400">Billing:</span>
                <span className={meta?.enable_billing ? 'text-green-600 font-bold' : 'text-gray-600 font-bold'}>
                  {meta?.enable_billing ? '✓ Enabled' : '✗ Disabled'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-600 dark:text-gray-400">Translation:</span>
                <span className={meta?.enable_translation ? 'text-green-600 font-bold' : 'text-gray-600 font-bold'}>
                  {meta?.enable_translation ? '✓ Enabled' : '✗ Disabled'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-600 dark:text-gray-400">Debug Mode:</span>
                <span className={meta?.debug ? 'text-orange-600 font-bold' : 'text-gray-600 font-bold'}>
                  {meta?.debug ? '✓ On' : '✗ Off'}
                </span>
              </div>
              <div className="flex justify-between items-center pt-2 border-t border-gray-200 dark:border-gray-800">
                <span className="text-gray-600 dark:text-gray-400">Version:</span>
                <span className="font-mono text-sm text-gray-900 dark:text-gray-100">{meta?.version}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Feature Flag Scenarios */}
      <div>
        <h2 className="text-2xl font-bold mb-4">Common Configurations</h2>
        <div className="grid grid-cols-1 gap-4">
          {FEATURE_FLAG_SCENARIOS.map((scenario) => (
            <div
              key={scenario.name}
              className="bg-white dark:bg-gray-950 rounded-lg border border-gray-200 dark:border-gray-800 p-6 hover:shadow-lg transition-shadow"
            >
              <h3 className="text-lg font-bold mb-4 text-gray-900 dark:text-white">{scenario.name}</h3>

              {/* Configuration */}
              <div className="mb-4">
                <h4 className="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-2">Configuration</h4>
                <div className="bg-gray-100 dark:bg-gray-900 p-3 rounded-md font-mono text-sm space-y-1 border border-gray-200 dark:border-gray-800">
                  {Object.entries(scenario.config).map(([key, value]) => (
                    <div key={key} className="flex justify-between gap-4">
                      <span className="text-gray-900 dark:text-gray-100">{key}</span>
                      <span className="text-gray-500">=</span>
                      <span className="text-green-600 dark:text-green-400">{String(value)}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Behavior */}
              <div className="mb-4">
                <h4 className="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-2">Behavior</h4>
                <p className="text-sm text-gray-700 dark:text-gray-300">{scenario.behavior}</p>
              </div>

              {/* Use Case */}
              <div>
                <h4 className="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-2">Use Case</h4>
                <p className="text-sm text-gray-700 dark:text-gray-300 italic">{scenario.useCase}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Reference Table */}
      <div>
        <h2 className="text-2xl font-bold mb-4">Feature Flag Reference</h2>
        <div className="bg-white dark:bg-gray-950 rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800">
                <tr>
                  <th className="text-left py-3 px-4 font-semibold text-gray-900 dark:text-white">Flag Name</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-900 dark:text-white">Type</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-900 dark:text-white">Default</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-900 dark:text-white">Purpose</th>
                </tr>
              </thead>
              <tbody>
                {[
                  {
                    name: 'ENABLE_USER_API_KEYS',
                    type: 'boolean',
                    default: 'false',
                    purpose: 'Allow users to provide their own API keys',
                  },
                  {
                    name: 'API_KEY_ALLOWED_EMAILS',
                    type: 'List[str]',
                    default: '[]',
                    purpose: 'Whitelist of emails exempt from needing their own API key',
                  },
                  {
                    name: 'ENABLE_API_KEYS_MENU',
                    type: 'boolean',
                    default: 'false',
                    purpose: 'Show API keys management in user settings',
                  },
                  {
                    name: 'ENABLE_BILLING',
                    type: 'boolean',
                    default: 'false',
                    purpose: 'Enable billing and payment features',
                  },
                  {
                    name: 'BILLING_DISABLED_MESSAGE',
                    type: 'string',
                    default: '"Billing is not available yet..."',
                    purpose: 'Custom message shown when billing is disabled',
                  },
                  {
                    name: 'ENABLE_TRANSLATION',
                    type: 'boolean',
                    default: 'false',
                    purpose: 'Enable multi-language support',
                  },
                  {
                    name: 'ENABLE_ASSEMBLYAI_DIARIZATION',
                    type: 'boolean',
                    default: 'false',
                    purpose: 'Enable speaker diarization with AssemblyAI',
                  },
                  {
                    name: 'DEBUG',
                    type: 'boolean',
                    default: 'false',
                    purpose: 'Enable debug mode with additional logging',
                  },
                ].map((flag, idx) => (
                  <tr
                    key={flag.name}
                    className={`border-b border-gray-200 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900 ${
                      idx % 2 === 0 ? '' : 'bg-gray-50 dark:bg-gray-900/50'
                    }`}
                  >
                    <td className="py-3 px-4 font-mono text-gray-900 dark:text-gray-100">{flag.name}</td>
                    <td className="py-3 px-4 text-gray-700 dark:text-gray-300">{flag.type}</td>
                    <td className="py-3 px-4 font-mono text-gray-700 dark:text-gray-300">{flag.default}</td>
                    <td className="py-3 px-4 text-gray-700 dark:text-gray-300">{flag.purpose}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Important Notes */}
      <div className="bg-blue-50 dark:bg-blue-950 rounded-lg border border-blue-200 dark:border-blue-800 p-6">
        <h3 className="text-lg font-bold mb-4 text-blue-900 dark:text-blue-100">💡 Important Notes</h3>
        <div className="space-y-3 text-sm text-blue-800 dark:text-blue-200">
          <p>
            <strong>API_KEY_ALLOWED_EMAILS Logic:</strong> When <code className="bg-blue-100 dark:bg-blue-900 px-2 py-1 rounded">ENABLE_USER_API_KEYS=true</code>, if this list is empty, <strong>ALL users must provide their own key</strong>. If populated with emails, only those emails get free access.
          </p>
          <p>
            <strong>Configuration:</strong> All flags are set via environment variables in your <code className="bg-blue-100 dark:bg-blue-900 px-2 py-1 rounded">.env</code> file.
          </p>
          <p>
            <strong>Frontend Sync:</strong> Changes to these flags require server restart for the frontend to pick up the new values.
          </p>
        </div>
      </div>
    </div>
  );
}
