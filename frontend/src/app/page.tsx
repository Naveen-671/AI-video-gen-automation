'use client';

import React, { useState, useEffect } from 'react';

interface SystemResources {
  available_ram_gib: number;
  free_disk_gb: number;
  min_ram_threshold_gib: number;
  min_disk_threshold_gb: number;
  ram_ok: boolean;
  disk_ok: boolean;
  can_process_jobs: boolean;
}

interface HealthData {
  status: string;
  db_connected: boolean;
  global_pause: boolean;
  resources: SystemResources;
  enabled_cost_classes: string[];
  active_jobs_count: number;
}

interface JobData {
  id: string;
  stage: string;
  status: string;
  attempts: number;
  max_attempts: number;
  idempotency_key: string;
  lease_expires_at?: string;
  created_at: string;
}

export default function MissionControl() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [jobs, setJobs] = useState<JobData[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [pauseLoading, setPauseLoading] = useState<boolean>(false);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [hRes, jRes] = await Promise.all([
        fetch('/health'),
        fetch('/jobs')
      ]);
      
      if (!hRes.ok) throw new Error(`Health check failed: ${hRes.status}`);
      if (!jRes.ok) throw new Error(`Jobs fetch failed: ${jRes.status}`);
      
      const hData: HealthData = await hRes.json();
      const jData: JobData[] = await jRes.json();
      
      setHealth(hData);
      setJobs(jData);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const togglePause = async () => {
    if (!health) return;
    try {
      setPauseLoading(true);
      const target = !health.global_pause;
      const res = await fetch('/pause', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paused: target })
      });
      if (res.ok) {
        await fetchData();
      }
    } catch (err: any) {
      alert(`Error toggling pause: ${err.message}`);
    } finally {
      setPauseLoading(false);
    }
  };

  return (
    <main style={{ maxWidth: '1200px', margin: '0 auto', padding: '2rem 1.5rem' }}>
      {/* Header */}
      <header style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingBottom: '1.5rem',
        borderBottom: '1px solid var(--border-color)',
        marginBottom: '2rem'
      }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>
            AI Shorts &amp; Reels Factory
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: '0.25rem' }}>
            Mission Control · Single-Worker Deterministic Pipeline · 127.0.0.1
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <button
            onClick={togglePause}
            disabled={pauseLoading || !health}
            style={{
              padding: '0.5rem 1rem',
              borderRadius: '6px',
              border: '1px solid',
              borderColor: health?.global_pause ? 'var(--accent-rose)' : 'var(--accent-cyan)',
              backgroundColor: health?.global_pause ? 'rgba(244, 63, 94, 0.15)' : 'rgba(6, 182, 212, 0.15)',
              color: health?.global_pause ? '#fda4af' : '#67e8f9',
              fontWeight: 600,
              fontSize: '0.875rem'
            }}
          >
            {pauseLoading ? 'Updating...' : (health?.global_pause ? '⏸ Global Paused (Click to Resume)' : '▶ System Active (Click to Pause)')}
          </button>
          
          <button
            onClick={fetchData}
            style={{
              padding: '0.5rem 0.85rem',
              borderRadius: '6px',
              border: '1px solid var(--border-color)',
              backgroundColor: 'var(--bg-card)',
              color: 'var(--text-secondary)',
              fontSize: '0.875rem'
            }}
          >
            Refresh
          </button>
        </div>
      </header>

      {/* System Status Cards */}
      <section style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
        gap: '1.25rem',
        marginBottom: '2.5rem'
      }}>
        <div style={{
          backgroundColor: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '8px',
          padding: '1.25rem'
        }}>
          <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>
            Pipeline State
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.5rem' }}>
            <span style={{
              display: 'inline-block',
              width: '10px',
              height: '10px',
              borderRadius: '50%',
              backgroundColor: health?.status === 'HEALTHY' ? 'var(--accent-emerald)' : 'var(--accent-rose)'
            }} />
            <h3 style={{ fontSize: '1.25rem', fontWeight: 600 }}>{health?.status || 'CONNECTING...'}</h3>
          </div>
          <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            SQLite WAL: {health?.db_connected ? 'Connected' : 'Disconnected'}
          </p>
        </div>

        <div style={{
          backgroundColor: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '8px',
          padding: '1.25rem'
        }}>
          <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>
            Host RAM Headroom
          </span>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem', marginTop: '0.5rem' }}>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 600 }}>
              {health?.resources.available_ram_gib ?? '...'} GiB
            </h3>
            <span style={{ fontSize: '0.8125rem', color: health?.resources.ram_ok ? 'var(--accent-emerald)' : 'var(--accent-rose)' }}>
              (Min: {health?.resources.min_ram_threshold_gib} GiB)
            </span>
          </div>
          <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            Guardrail: {health?.resources.ram_ok ? 'Pass' : 'RAM LOW - Worker Paused'}
          </p>
        </div>

        <div style={{
          backgroundColor: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '8px',
          padding: '1.25rem'
        }}>
          <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>
            Free NVMe Disk
          </span>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem', marginTop: '0.5rem' }}>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 600 }}>
              {health?.resources.free_disk_gb ?? '...'} GB
            </h3>
            <span style={{ fontSize: '0.8125rem', color: health?.resources.disk_ok ? 'var(--accent-emerald)' : 'var(--accent-rose)' }}>
              (Min: {health?.resources.min_disk_threshold_gb} GB)
            </span>
          </div>
          <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            Guardrail: {health?.resources.disk_ok ? 'Pass' : 'DISK LOW - Worker Paused'}
          </p>
        </div>

        <div style={{
          backgroundColor: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: '8px',
          padding: '1.25rem'
        }}>
          <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>
            Cost Policy &amp; Providers
          </span>
          <div style={{ marginTop: '0.5rem' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--accent-emerald)' }}>
              Zero Recurring Cost
            </h3>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              Allowed: {health?.enabled_cost_classes.join(', ') || 'free_local, free_quota, manual'}
            </p>
          </div>
        </div>
      </section>

      {/* Job Queue Table */}
      <section style={{
        backgroundColor: 'var(--bg-card)',
        border: '1px solid var(--border-color)',
        borderRadius: '8px',
        padding: '1.5rem'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <div>
            <h2 style={{ fontSize: '1.125rem', fontWeight: 600 }}>Worker Job Queue</h2>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
              Single-worker slot · Database-backed lease &amp; heartbeat
            </p>
          </div>
          <span style={{
            fontSize: '0.8125rem',
            padding: '0.25rem 0.65rem',
            backgroundColor: 'var(--bg-secondary)',
            borderRadius: '4px',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)'
          }}>
            {jobs.length} jobs total
          </span>
        </div>

        {jobs.length === 0 ? (
          <div style={{
            padding: '2.5rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.875rem'
          }}>
            No jobs in queue. Submit a job via POST /jobs or pipeline trigger.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)', textAlign: 'left', color: 'var(--text-muted)' }}>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Stage</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Status</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Attempts</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Idempotency Key</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Created At</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <td style={{ padding: '0.75rem 0.5rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                      {job.stage}
                    </td>
                    <td style={{ padding: '0.75rem 0.5rem' }}>
                      <span style={{
                        display: 'inline-block',
                        padding: '0.2rem 0.5rem',
                        borderRadius: '4px',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        backgroundColor:
                          job.status === 'SUCCEEDED' ? 'rgba(16, 185, 129, 0.15)' :
                          job.status === 'RUNNING' || job.status === 'LEASED' ? 'rgba(6, 182, 212, 0.15)' :
                          job.status === 'QUEUED' ? 'rgba(245, 158, 11, 0.15)' : 'rgba(244, 63, 94, 0.15)',
                        color:
                          job.status === 'SUCCEEDED' ? '#6ee7b7' :
                          job.status === 'RUNNING' || job.status === 'LEASED' ? '#67e8f9' :
                          job.status === 'QUEUED' ? '#fcd34d' : '#fda4af'
                      }}>
                        {job.status}
                      </span>
                    </td>
                    <td style={{ padding: '0.75rem 0.5rem', fontFamily: 'var(--font-mono)' }}>
                      {job.attempts} / {job.max_attempts}
                    </td>
                    <td style={{ padding: '0.75rem 0.5rem', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                      {job.idempotency_key}
                    </td>
                    <td style={{ padding: '0.75rem 0.5rem', color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
                      {new Date(job.created_at).toLocaleTimeString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
