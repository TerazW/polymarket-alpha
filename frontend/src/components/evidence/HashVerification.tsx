'use client';

import { useState, useEffect } from 'react';

interface HashVerificationProps {
  storedHash: string;
  computedHash?: string;
  bundleId?: string;
  onVerify?: () => Promise<string>;  // Returns computed hash
}

type VerificationStatus = 'pending' | 'verifying' | 'match' | 'mismatch' | 'error';

/**
 * Hash Verification UI Component
 *
 * Displays comparison between stored and computed evidence bundle hash.
 * Provides visual feedback on verification status.
 *
 * "每一个证据包都可验证"
 */
export default function HashVerification({
  storedHash,
  computedHash: initialComputedHash,
  bundleId,
  onVerify,
}: HashVerificationProps) {
  const [status, setStatus] = useState<VerificationStatus>(
    initialComputedHash ?
      (initialComputedHash === storedHash ? 'match' : 'mismatch') :
      'pending'
  );
  const [computedHash, setComputedHash] = useState<string>(initialComputedHash || '');
  const [error, setError] = useState<string>('');
  const [verifiedAt, setVerifiedAt] = useState<Date | null>(null);

  // If computed hash is provided initially, check match
  useEffect(() => {
    if (initialComputedHash) {
      setComputedHash(initialComputedHash);
      setStatus(initialComputedHash === storedHash ? 'match' : 'mismatch');
      setVerifiedAt(new Date());
    }
  }, [initialComputedHash, storedHash]);

  const handleVerify = async () => {
    if (!onVerify) return;

    setStatus('verifying');
    setError('');

    try {
      const hash = await onVerify();
      setComputedHash(hash);
      setStatus(hash === storedHash ? 'match' : 'mismatch');
      setVerifiedAt(new Date());
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Verification failed');
    }
  };

  // Status indicator colors and icons
  const getStatusDisplay = () => {
    switch (status) {
      case 'pending':
        return {
          icon: '?',
          color: 'text-gray-400',
          bgColor: 'bg-gray-100',
          label: 'Not Verified',
        };
      case 'verifying':
        return {
          icon: '...',
          color: 'text-blue-500',
          bgColor: 'bg-blue-50',
          label: 'Verifying...',
        };
      case 'match':
        return {
          icon: '✓',
          color: 'text-green-600',
          bgColor: 'bg-green-50',
          label: 'Verified',
        };
      case 'mismatch':
        return {
          icon: '✗',
          color: 'text-red-600',
          bgColor: 'bg-red-50',
          label: 'Hash Mismatch',
        };
      case 'error':
        return {
          icon: '!',
          color: 'text-yellow-600',
          bgColor: 'bg-yellow-50',
          label: 'Error',
        };
    }
  };

  const statusDisplay = getStatusDisplay();

  return (
    <div className={`p-4 rounded-lg border ${statusDisplay.bgColor}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`text-xl font-bold ${statusDisplay.color}`}>
            {statusDisplay.icon}
          </span>
          <span className={`font-medium ${statusDisplay.color}`}>
            {statusDisplay.label}
          </span>
        </div>

        {onVerify && status !== 'verifying' && (
          <button
            onClick={handleVerify}
            className="px-3 py-1 text-sm bg-blue-500 text-white rounded hover:bg-blue-600 transition"
          >
            {status === 'pending' ? 'Verify Now' : 'Re-verify'}
          </button>
        )}
      </div>

      {/* Hash Display */}
      <div className="space-y-2 text-sm font-mono">
        {/* Stored Hash */}
        <div className="flex items-start gap-2">
          <span className="text-gray-500 w-20 flex-shrink-0">Stored:</span>
          <code className="text-gray-700 break-all">
            {storedHash || 'N/A'}
          </code>
        </div>

        {/* Computed Hash */}
        {computedHash && (
          <div className="flex items-start gap-2">
            <span className="text-gray-500 w-20 flex-shrink-0">Computed:</span>
            <code className={`break-all ${
              status === 'match' ? 'text-green-700' :
              status === 'mismatch' ? 'text-red-700' :
              'text-gray-700'
            }`}>
              {computedHash}
            </code>
          </div>
        )}
      </div>

      {/* Visual Hash Diff (on mismatch) */}
      {status === 'mismatch' && storedHash && computedHash && (
        <div className="mt-3 p-2 bg-red-100 rounded text-xs">
          <div className="text-red-700 font-medium mb-1">
            Hash Difference Detected
          </div>
          <div className="font-mono">
            {Array.from(storedHash).map((char, i) => (
              <span
                key={i}
                className={computedHash[i] !== char ? 'text-red-600 font-bold' : 'text-gray-500'}
              >
                {char}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div className="mt-2 text-red-600 text-sm">
          Error: {error}
        </div>
      )}

      {/* Verification Timestamp */}
      {verifiedAt && (
        <div className="mt-2 text-xs text-gray-400">
          Verified at: {verifiedAt.toLocaleString()}
        </div>
      )}

      {/* Bundle ID */}
      {bundleId && (
        <div className="mt-1 text-xs text-gray-400">
          Bundle: {bundleId}
        </div>
      )}
    </div>
  );
}


/**
 * Compact version for inline display
 */
export function HashVerificationBadge({
  storedHash,
  computedHash,
}: {
  storedHash: string;
  computedHash?: string;
}) {
  if (!computedHash) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-500">
        <span className="mr-1">?</span>
        Unverified
      </span>
    );
  }

  const matches = storedHash === computedHash;

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${
        matches
          ? 'bg-green-100 text-green-700'
          : 'bg-red-100 text-red-700'
      }`}
      title={`Stored: ${storedHash}\nComputed: ${computedHash}`}
    >
      <span className="mr-1">{matches ? '✓' : '✗'}</span>
      {matches ? 'Verified' : 'Mismatch'}
    </span>
  );
}


/**
 * Full audit panel with detailed checks
 */
export function AuditPanel({
  bundleHash,
  tokenId,
  t0,
  checks,
}: {
  bundleHash: string;
  tokenId: string;
  t0: number;
  checks: Array<{
    name: string;
    status: 'pass' | 'fail' | 'skip';
    message?: string;
  }>;
}) {
  const passCount = checks.filter(c => c.status === 'pass').length;
  const failCount = checks.filter(c => c.status === 'fail').length;
  const allPassed = failCount === 0;

  return (
    <div className={`p-4 rounded-lg border ${allPassed ? 'bg-green-50' : 'bg-red-50'}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-bold">Audit Verification</h3>
        <span className={`px-2 py-1 rounded text-sm ${
          allPassed ? 'bg-green-200 text-green-800' : 'bg-red-200 text-red-800'
        }`}>
          {passCount}/{checks.length} Passed
        </span>
      </div>

      <div className="text-sm space-y-1 mb-4">
        <div className="text-gray-600">Token: <span className="font-mono">{tokenId}</span></div>
        <div className="text-gray-600">T0: <span className="font-mono">{new Date(t0).toISOString()}</span></div>
        <div className="text-gray-600">Hash: <span className="font-mono text-xs">{bundleHash}</span></div>
      </div>

      <div className="space-y-2">
        {checks.map((check, i) => (
          <div
            key={i}
            className={`flex items-center gap-2 p-2 rounded ${
              check.status === 'pass' ? 'bg-green-100' :
              check.status === 'fail' ? 'bg-red-100' :
              'bg-gray-100'
            }`}
          >
            <span className={`text-lg ${
              check.status === 'pass' ? 'text-green-600' :
              check.status === 'fail' ? 'text-red-600' :
              'text-gray-400'
            }`}>
              {check.status === 'pass' ? '✓' : check.status === 'fail' ? '✗' : '−'}
            </span>
            <span className="flex-1">{check.name}</span>
            {check.message && (
              <span className="text-xs text-gray-500">{check.message}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
