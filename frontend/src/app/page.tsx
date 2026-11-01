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

interface FactClaim {
  id: string;
  source_id?: string;
  claim_text: string;
  quote_excerpt: string;
  evidence_status: string;
  uncertainty_rationale?: string;
  source_url?: string;
  source_title?: string;
  created_at: string;
}

interface FactSource {
  id: string;
  url: string;
  title: string;
  published_date?: string;
  raw_excerpt?: string;
  http_status: number;
}

interface Scene {
  id?: string;
  scene_index: number;
  scene_title: string;
  narration_text: string;
  caption_text: string;
  duration_seconds: number;
  visual_asset_path?: string;
  motion_preset?: string;
  asset_provenance_id?: string;
  supporting_claim_ids?: string[];
}

interface AssetProvenance {
  id: string;
  project_id: string;
  scene_index: number;
  asset_type: string;
  source_url?: string;
  author?: string;
  license?: string;
  attribution_text?: string;
  local_path: string;
  sha256_checksum: string;
  associated_claim_id?: string;
  source_asset_id?: string;
  source_page_url?: string;
  license_url?: string;
  media_type?: string;
  original_width?: number;
  original_height?: number;
  original_duration?: number;
  file_size_bytes?: number;
  rights_status?: string;
  crop_transform?: string;
  selection_reason?: string;
  created_at?: string;
}

interface EditorialReview {
  id: string;
  project_id: string;
  render_id?: string;
  overall_status: string;
  score: number;
  hook_evaluation?: any;
  pacing_evaluation?: any;
  relevance_evaluation?: any;
  audio_evaluation?: any;
  warnings?: Array<{ category: string; severity: string; message: string; scene_index?: number }>;
  created_at?: string;
}

interface Project {
  id: string;
  title: string;
  topic: string;
  target_audience: string;
  language: string;
  target_duration: number;
  content_format: string;
  narrative_archetype?: string;
  narration_mode: string;
  narration_voice?: string;
  narration_audio_path?: string;
  status: string;
  current_render_id?: string;
  render_checksum?: string;
  approval_status?: string;
  created_at: string;
  scenes?: Scene[];
  current_render?: any;
  active_approval?: any;
  fact_claims?: FactClaim[];
  fact_sources?: FactSource[];
  asset_provenances?: AssetProvenance[];
  editorial_review?: EditorialReview;
}

interface JobData {
  id: string;
  stage: string;
  status: string;
  attempts: number;
  max_attempts: number;
  idempotency_key: string;
  created_at: string;
}

export default function MissionControl() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [jobs, setJobs] = useState<JobData[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [pauseLoading, setPauseLoading] = useState<boolean>(false);
  const [renderLoading, setRenderLoading] = useState<boolean>(false);

  // New Project Form State
  const [showNewProject, setShowNewProject] = useState<boolean>(false);
  const [newTopic, setNewTopic] = useState<string>('How Quantum Computers Factor Numbers');
  const [newTitle, setNewTitle] = useState<string>('');
  const [newDuration, setNewDuration] = useState<number>(15);
  const [newFormat, setNewFormat] = useState<string>('explainer');
  const [newArchetype, setNewArchetype] = useState<string>('CURIOSITY_GAP');
  const [newNarrationMode, setNewNarrationMode] = useState<string>('local_tts');
  const [newVoice, setNewVoice] = useState<string>('af_bella');

  // Storyboard & Research State
  const [editableScenes, setEditableScenes] = useState<Scene[]>([]);
  const [storyboardSavedMsg, setStoryboardSavedMsg] = useState<string | null>(null);
  const [researchLoading, setResearchLoading] = useState<boolean>(false);
  const [activeArchetype, setActiveArchetype] = useState<string>('CURIOSITY_GAP');
  const [validationReport, setValidationReport] = useState<any>(null);

  // Stage 6: YouTube OAuth & Guarded Publishing State
  const [youtubeStatus, setYoutubeStatus] = useState<any>(null);
  const [publishLoading, setPublishLoading] = useState<boolean>(false);
  const [publishResult, setPublishResult] = useState<any>(null);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [showConfigModal, setShowConfigModal] = useState<boolean>(false);
  const [clientIdInput, setClientIdInput] = useState<string>('');
  const [clientSecretInput, setClientSecretInput] = useState<string>('');
  const [publishTitle, setPublishTitle] = useState<string>('');
  const [publishDesc, setPublishDesc] = useState<string>('');

  // Track 1: Google Flow Handoff & Ingestion State
  const [showFlowModal, setShowFlowModal] = useState<boolean>(false);
  const [flowManifest, setFlowManifest] = useState<any>(null);
  const [flowCopyNotice, setFlowCopyNotice] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [hRes, jRes, pRes] = await Promise.all([
        fetch('/health'),
        fetch('/jobs'),
        fetch('/projects')
      ]);

      if (!hRes.ok) throw new Error(`Health check failed: ${hRes.status}`);
      if (!jRes.ok) throw new Error(`Jobs fetch failed: ${jRes.status}`);
      if (!pRes.ok) throw new Error(`Projects fetch failed: ${pRes.status}`);

      const hData: HealthData = await hRes.json();
      const jData: JobData[] = await jRes.json();
      const pData: Project[] = await pRes.json();

      setHealth(hData);
      setJobs(jData);
      setProjects(pData);

      // Fetch YouTube OAuth status
      try {
        const ytRes = await fetch('/api/v1/auth/youtube/status');
        if (ytRes.ok) {
          const ytData = await ytRes.json();
          setYoutubeStatus(ytData);
        }
      } catch (e) {
        console.debug('Failed to fetch YouTube status:', e);
      }

      setError(null);

      // If a project is selected, refresh its details
      if (selectedProjectId) {
        const detailRes = await fetch(`/projects/${selectedProjectId}`);
        if (detailRes.ok) {
          const detailData: Project = await detailRes.json();
          setSelectedProject(detailData);
          setEditableScenes(detailData.scenes || []);
        }
      } else if (pData.length > 0 && !selectedProjectId) {
        // Select first project by default
        selectProject(pData[0].id);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  };

  const selectProject = async (id: string) => {
    setSelectedProjectId(id);
    setStoryboardSavedMsg(null);
    try {
      const res = await fetch(`/projects/${id}`);
      if (res.ok) {
        const data: Project = await res.json();
        setSelectedProject(data);
        setEditableScenes(data.scenes || []);
      }
    } catch (err: any) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 6000);
    return () => clearInterval(interval);
  }, [selectedProjectId]);

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

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch('/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: newTopic,
          title: newTitle || undefined,
          target_duration: Number(newDuration),
          content_format: newFormat,
          narrative_archetype: newArchetype,
          narration_mode: newNarrationMode,
          narration_voice: newVoice
        })
      });
      if (!res.ok) throw new Error(`Project creation failed: ${res.status}`);
      const data = await res.json();
      setShowNewProject(false);
      await fetchData();
      selectProject(data.project_id);
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleTriggerResearch = async () => {
    if (!selectedProjectId) return;
    setResearchLoading(true);
    setValidationReport(null);
    try {
      const res = await fetch(`/projects/${selectedProjectId}/research?archetype=${activeArchetype}`, {
        method: 'POST'
      });
      if (!res.ok) throw new Error(`Research failed: ${res.status}`);
      const data = await res.json();
      setValidationReport(data.validation);
      await selectProject(selectedProjectId);
      await fetchData();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setResearchLoading(false);
    }
  };

  const handleSaveStoryboard = async () => {
    if (!selectedProjectId) return;
    try {
      const res = await fetch(`/projects/${selectedProjectId}/storyboard`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenes: editableScenes })
      });
      if (!res.ok) throw new Error('Failed to update storyboard');
      setStoryboardSavedMsg('Storyboard saved! Any previous render approval was superseded.');
      await selectProject(selectedProjectId);
      await fetchData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleOpenFlowPrompts = async () => {
    if (!selectedProjectId) return;
    try {
      const res = await fetch(`/projects/${selectedProjectId}/flow-prompts`);
      if (!res.ok) throw new Error('Failed to fetch Flow prompts');
      const data = await res.json();
      setFlowManifest(data.manifest);
      setShowFlowModal(true);
    } catch (err: any) {
      alert(err.message || 'Error fetching Flow prompts');
    }
  };

  const handleCopyFlowPrompt = (text: string, sceneIdx: number) => {
    navigator.clipboard.writeText(text);
    setFlowCopyNotice(`Copied prompt for Scene ${sceneIdx + 1} to clipboard!`);
    setTimeout(() => setFlowCopyNotice(null), 3000);
  };

  const handleImportFlowVideo = async (e: React.ChangeEvent<HTMLInputElement>, sceneId: string) => {
    const file = e.target.files?.[0];
    if (!file || !selectedProjectId) return;
    try {
      setStoryboardSavedMsg(`Validating and importing ${file.name}...`);
      const res = await fetch(`/projects/${selectedProjectId}/scenes/${sceneId}/import-flow-video?filename=${encodeURIComponent(file.name)}`, {
        method: 'POST',
        body: file
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Import validation failed');
      }
      const data = await res.json();
      setStoryboardSavedMsg(`Flow video imported! Status: ${data.validation.status}. Previous approvals invalidated.`);
      await selectProject(selectedProjectId);
      await fetchData();
    } catch (err: any) {
      alert(`Flow Video Import Error: ${err.message}`);
      setStoryboardSavedMsg(null);
    }
  };

  const handleTriggerRender = async (width: number = 1080, height: number = 1920) => {
    if (!selectedProjectId) return;
    try {
      setRenderLoading(true);
      const res = await fetch(`/projects/${selectedProjectId}/render?width=${width}&height=${height}&enable_motion=true&enable_bg_music=true&enable_video_ingest=true&enable_transitions=true&transition_duration=0.5`, {
        method: 'POST'
      });
      if (!res.ok) throw new Error('Failed to queue render');
      await fetchData();
      await selectProject(selectedProjectId);
    } catch (err: any) {
      alert(err.message);
    } finally {
      setRenderLoading(false);
    }
  };

  const handleApproveRender = async (renderId: string) => {
    try {
      const res = await fetch(`/renders/${renderId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'APPROVED', reviewer: 'human_operator' })
      });
      if (!res.ok) throw new Error('Approval failed');
      await selectProject(selectedProjectId!);
      await fetchData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleRejectRender = async (renderId: string) => {
    const reason = prompt('Please enter rejection feedback / reason:');
    if (reason === null) return;
    try {
      const res = await fetch(`/renders/${renderId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'REJECTED', notes: reason, reviewer: 'human_operator' })
      });
      if (!res.ok) throw new Error('Rejection failed');
      await selectProject(selectedProjectId!);
      await fetchData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleConfigureYouTube = async () => {
    if (!clientIdInput.trim() || !clientSecretInput.trim()) {
      alert('Please provide both Client ID and Client Secret.');
      return;
    }
    try {
      const res = await fetch('/api/v1/auth/youtube/configure', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: clientIdInput.trim(), client_secret: clientSecretInput.trim() })
      });
      if (!res.ok) throw new Error('Failed to configure Google client credentials.');
      setShowConfigModal(false);
      setClientIdInput('');
      setClientSecretInput('');
      await fetchData();
    } catch (e: any) {
      alert(e.message);
    }
  };

  const handleConnectYouTube = async () => {
    try {
      const res = await fetch('/api/v1/auth/youtube/authorize');
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to generate authorization URL');
      }
      const data = await res.json();
      window.location.href = data.authorization_url;
    } catch (e: any) {
      alert(e.message);
    }
  };

  const handleDisconnectYouTube = async () => {
    if (!confirm('Are you sure you want to disconnect YouTube?')) return;
    try {
      await fetch('/api/v1/auth/youtube/disconnect', { method: 'POST' });
      await fetchData();
    } catch (e: any) {
      alert(e.message);
    }
  };

  const handleUploadToYouTube = async () => {
    if (!selectedProject || !selectedProject.current_render) return;
    try {
      setPublishLoading(true);
      setPublishError(null);
      setPublishResult(null);
      const res = await fetch('/api/v1/publishing/youtube/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: selectedProject.id,
          render_id: selectedProject.current_render.id,
          title: publishTitle || selectedProject.title,
          description: publishDesc || selectedProject.topic,
          privacy_status: 'private'
        })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Upload failed');
      }
      setPublishResult(data);
      await fetchData();
      if (selectedProjectId) {
        await selectProject(selectedProjectId);
      }
    } catch (e: any) {
      setPublishError(e.message);
    } finally {
      setPublishLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>, sceneId?: string, assetType: string = 'image') => {
    if (!selectedProjectId || !e.target.files || e.target.files.length === 0) return;
    const file = e.target.files[0];
    try {
      const arrayBuffer = await file.arrayBuffer();
      const url = `/projects/${selectedProjectId}/assets?filename=${encodeURIComponent(file.name)}&asset_type=${assetType}${sceneId ? `&scene_id=${sceneId}` : ''}`;
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: arrayBuffer
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Upload failed');
      }
      alert(`Asset uploaded: ${file.name}`);
      await selectProject(selectedProjectId);
    } catch (err: any) {
      alert(`Upload error: ${err.message}`);
    }
  };

  return (
    <main style={{ maxWidth: '1350px', margin: '0 auto', padding: '2rem 1.5rem' }}>
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
          <h1 style={{ fontSize: '1.6rem', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>
            AI Shorts &amp; Reels Factory
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: '0.25rem' }}>
            Mission Control · End-to-End Local Pipeline · Deterministic Human Approval Gate
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <button
            onClick={() => setShowNewProject(!showNewProject)}
            style={{
              padding: '0.5rem 1.1rem',
              borderRadius: '6px',
              border: 'none',
              backgroundColor: 'var(--accent-cyan)',
              color: '#0b0f17',
              fontWeight: 700,
              fontSize: '0.875rem'
            }}
          >
            + New Video Project
          </button>

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
            {pauseLoading ? 'Updating...' : (health?.global_pause ? '⏸ Paused (Click to Resume)' : '▶ Active (Click to Pause)')}
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

      {/* New Project Modal/Drawer */}
      {showNewProject && (
        <section style={{
          backgroundColor: 'var(--bg-card)',
          border: '1px solid var(--accent-cyan)',
          borderRadius: '8px',
          padding: '1.5rem',
          marginBottom: '2rem'
        }}>
          <h2 style={{ fontSize: '1.125rem', fontWeight: 600, marginBottom: '1rem' }}>Create New Video Project</h2>
          <form onSubmit={handleCreateProject} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>Topic</label>
              <input
                type="text"
                value={newTopic}
                onChange={(e) => setNewTopic(e.target.value)}
                required
                style={{ width: '100%', padding: '0.5rem', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: '#fff' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>Title (Optional)</label>
              <input
                type="text"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="Auto-generated if blank"
                style={{ width: '100%', padding: '0.5rem', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: '#fff' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>Target Duration (Seconds)</label>
              <input
                type="number"
                value={newDuration}
                onChange={(e) => setNewDuration(Number(e.target.value))}
                min="9"
                max="60"
                style={{ width: '100%', padding: '0.5rem', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: '#fff' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>Narrative Archetype</label>
              <select
                value={newArchetype}
                onChange={(e) => setNewArchetype(e.target.value)}
                style={{ width: '100%', padding: '0.5rem', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: '#fff' }}
              >
                <option value="CURIOSITY_GAP">Curiosity Gap (Mystery → Reveal → Payoff)</option>
                <option value="HISTORICAL_MICRO_EPIC">Historical Micro-Epic (Crisis → Breakthrough → Legacy)</option>
                <option value="DISCONFIRMATION_JOURNEY">Disconfirmation Journey (Common Myth → Critical Counter-Evidence)</option>
                <option value="SCALE_SHOCK">Scale Shock (Familiar Object → Cosmic Perspective)</option>
              </select>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>Narration Mode</label>
              <select
                value={newNarrationMode}
                onChange={(e) => setNewNarrationMode(e.target.value)}
                style={{ width: '100%', padding: '0.5rem', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: '#fff' }}
              >
                <option value="local_tts">Local Neural TTS (Kokoro-82M)</option>
                <option value="silent">Silent (with Captions)</option>
                <option value="manual_audio">Manual Audio (User Uploaded Voiceover)</option>
              </select>
            </div>
            {newNarrationMode === 'local_tts' && (
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>TTS Voice</label>
                <select
                  value={newVoice}
                  onChange={(e) => setNewVoice(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: '#fff' }}
                >
                  <option value="af_bella">af_bella (US Female - Default)</option>
                  <option value="af_heart">af_heart (US Female - Warm)</option>
                  <option value="af_nicole">af_nicole (US Female - Expressive)</option>
                  <option value="am_adam">am_adam (US Male)</option>
                  <option value="bm_george">bm_george (UK Male)</option>
                  <option value="bf_emma">bf_emma (UK Female)</option>
                  <option value="hf_alpha">hf_alpha (Hindi Female)</option>
                  <option value="hm_omega">hm_omega (Hindi Male)</option>
                </select>
              </div>
            )}
            <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '0.75rem', marginTop: '0.5rem' }}>
              <button
                type="submit"
                style={{ padding: '0.5rem 1.25rem', backgroundColor: 'var(--accent-emerald)', border: 'none', borderRadius: '4px', color: '#0b0f17', fontWeight: 700 }}
              >
                Generate Storyboard
              </button>
              <button
                type="button"
                onClick={() => setShowNewProject(false)}
                style={{ padding: '0.5rem 1rem', backgroundColor: 'transparent', border: '1px solid var(--border-color)', borderRadius: '4px', color: 'var(--text-secondary)' }}
              >
                Cancel
              </button>
            </div>
          </form>
        </section>
      )}

      {/* System Status Cards */}
      <section style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
        gap: '1rem',
        marginBottom: '2rem'
      }}>
        <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '1rem' }}>
          <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>System State</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.25rem' }}>
            <span style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: health?.status === 'HEALTHY' ? 'var(--accent-emerald)' : 'var(--accent-rose)' }} />
            <span style={{ fontSize: '1.1rem', fontWeight: 600 }}>{health?.status || 'CONNECTING...'}</span>
          </div>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>SQLite WAL · Active Jobs: {health?.active_jobs_count || 0}</p>
        </div>

        <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '1rem' }}>
          <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>Host RAM Headroom</span>
          <div style={{ fontSize: '1.1rem', fontWeight: 600, marginTop: '0.25rem' }}>
            {health?.resources.available_ram_gib ?? '...'} GiB
            <span style={{ fontSize: '0.75rem', color: health?.resources.ram_ok ? 'var(--accent-emerald)' : 'var(--accent-rose)', marginLeft: '0.5rem' }}>
              (Min: {health?.resources.min_ram_threshold_gib} GiB)
            </span>
          </div>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>Worker Guardrail: {health?.resources.ram_ok ? 'Optimal' : 'Low Memory'}</p>
        </div>

        <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '1rem' }}>
          <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>Free NVMe Disk</span>
          <div style={{ fontSize: '1.1rem', fontWeight: 600, marginTop: '0.25rem' }}>
            {health?.resources.free_disk_gb ?? '...'} GB
            <span style={{ fontSize: '0.75rem', color: health?.resources.disk_ok ? 'var(--accent-emerald)' : 'var(--accent-rose)', marginLeft: '0.5rem' }}>
              (Min: {health?.resources.min_disk_threshold_gb} GB)
            </span>
          </div>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>Guardrail: {health?.resources.disk_ok ? 'Optimal' : 'Low Disk'}</p>
        </div>

        <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '1rem' }}>
          <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>Cost Policy</span>
          <div style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--accent-emerald)', marginTop: '0.25rem' }}>Zero Added Cost</div>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>metered providers prohibited</p>
        </div>
      </section>

      {/* Main Workspace Grid */}
      <section style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '1.5rem', marginBottom: '2.5rem' }}>
        {/* Projects Sidebar */}
        <aside style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '1.25rem', height: 'fit-content' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <h2 style={{ fontSize: '1rem', fontWeight: 600 }}>Video Projects</h2>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{projects.length} total</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {projects.map((p) => {
              const isSelected = p.id === selectedProjectId;
              return (
                <div
                  key={p.id}
                  onClick={() => selectProject(p.id)}
                  style={{
                    padding: '0.75rem',
                    borderRadius: '6px',
                    border: '1px solid',
                    borderColor: isSelected ? 'var(--accent-cyan)' : 'var(--border-color)',
                    backgroundColor: isSelected ? 'rgba(6, 182, 212, 0.08)' : 'var(--bg-primary)',
                    cursor: 'pointer'
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: '0.875rem', color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
                    {p.title}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.75rem' }}>
                    <span style={{ color: 'var(--text-muted)' }}>{p.target_duration}s · {p.content_format}</span>
                    <span style={{
                      padding: '0.15rem 0.4rem',
                      borderRadius: '4px',
                      fontWeight: 600,
                      backgroundColor:
                        p.status === 'APPROVED' ? 'rgba(16, 185, 129, 0.2)' :
                        p.status === 'AWAITING_APPROVAL' ? 'rgba(245, 158, 11, 0.2)' : 'rgba(255, 255, 255, 0.08)',
                      color:
                        p.status === 'APPROVED' ? '#6ee7b7' :
                        p.status === 'AWAITING_APPROVAL' ? '#fcd34d' : 'var(--text-secondary)'
                    }}>
                      {p.status}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </aside>

        {/* Project Detail & Production Panel */}
        <section style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '1.5rem' }}>
          {selectedProject ? (
            <div>
              {/* Detail Header */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', borderBottom: '1px solid var(--border-color)', paddingBottom: '1rem', marginBottom: '1.5rem' }}>
                <div>
                  <h2 style={{ fontSize: '1.3rem', fontWeight: 700 }}>{selectedProject.title}</h2>
                  <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                    Topic: {selectedProject.topic} · Duration: {selectedProject.target_duration}s · Archetype: {selectedProject.narrative_archetype || 'CURIOSITY_GAP'} · Narration: {selectedProject.narration_mode}
                  </p>
                </div>

                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                  <select
                    value={activeArchetype}
                    onChange={(e) => setActiveArchetype(e.target.value)}
                    style={{ padding: '0.4rem 0.6rem', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '6px', color: '#fff', fontSize: '0.8125rem' }}
                  >
                    <option value="CURIOSITY_GAP">Curiosity Gap</option>
                    <option value="HISTORICAL_MICRO_EPIC">Historical Micro-Epic</option>
                    <option value="DISCONFIRMATION_JOURNEY">Disconfirmation Journey</option>
                    <option value="SCALE_SHOCK">Scale Shock</option>
                  </select>

                  <button
                    onClick={handleTriggerResearch}
                    disabled={researchLoading}
                    style={{
                      padding: '0.5rem 0.85rem',
                      borderRadius: '6px',
                      border: '1px solid var(--accent-cyan)',
                      backgroundColor: 'rgba(6, 182, 212, 0.1)',
                      color: 'var(--accent-cyan)',
                      fontWeight: 600,
                      fontSize: '0.8125rem'
                    }}
                  >
                    {researchLoading ? 'Researching...' : '🔍 Research & Propose Beats'}
                  </button>

                  <button
                    onClick={() => handleTriggerRender(1080, 1920)}
                    disabled={renderLoading}
                    style={{
                      padding: '0.5rem 1rem',
                      borderRadius: '6px',
                      border: 'none',
                      backgroundColor: 'var(--accent-emerald)',
                      color: '#0b0f17',
                      fontWeight: 700,
                      fontSize: '0.875rem'
                    }}
                  >
                    {renderLoading ? 'Rendering...' : '🎬 Render 1080p (Motion + Audio)'}
                  </button>

                  <button
                    onClick={() => handleTriggerRender(720, 1280)}
                    disabled={renderLoading}
                    style={{
                      padding: '0.5rem 0.75rem',
                      borderRadius: '6px',
                      border: '1px solid var(--border-color)',
                      backgroundColor: 'var(--bg-card)',
                      color: 'var(--text-secondary)',
                      fontWeight: 600,
                      fontSize: '0.8125rem'
                    }}
                  >
                    Draft 720p
                  </button>
                </div>
              </div>

              {/* Render Preview & Approval Gate (If Render exists) */}
              {selectedProject.current_render ? (
                <div style={{
                  backgroundColor: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: '8px',
                  padding: '1.25rem',
                  marginBottom: '1.5rem',
                  display: 'grid',
                  gridTemplateColumns: '240px 1fr',
                  gap: '1.5rem'
                }}>
                  {/* HTML5 Video Player */}
                  <div style={{ borderRadius: '6px', overflow: 'hidden', backgroundColor: '#000', display: 'flex', justifyContent: 'center' }}>
                    <video
                      controls
                      src={`/renders/${selectedProject.current_render.id}/file`}
                      style={{ maxHeight: '380px', width: 'auto', aspectRatio: '9/16' }}
                    />
                  </div>

                  {/* Render Metadata & Approval Controls */}
                  <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                        <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>Active Render Artifact</span>
                        <span style={{
                          padding: '0.15rem 0.5rem',
                          borderRadius: '4px',
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          backgroundColor:
                            selectedProject.status === 'APPROVED' ? 'rgba(16, 185, 129, 0.2)' :
                            selectedProject.status === 'REJECTED' ? 'rgba(244, 63, 94, 0.2)' : 'rgba(245, 158, 11, 0.2)',
                          color:
                            selectedProject.status === 'APPROVED' ? '#6ee7b7' :
                            selectedProject.status === 'REJECTED' ? '#fda4af' : '#fcd34d'
                        }}>
                          {selectedProject.status}
                        </span>
                      </div>

                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.75rem', wordBreak: 'break-all' }}>
                        SHA-256 Checksum: <br />
                        <span style={{ color: 'var(--accent-cyan)' }}>{selectedProject.current_render.render_checksum}</span>
                      </div>

                      <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
                        QA Status: <strong style={{ color: '#fff' }}>{selectedProject.current_render.qa_status}</strong> · Vertical 9:16
                      </p>
                    </div>

                    <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '1rem', marginTop: '1rem' }}>
                      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                        <a
                          href={`/renders/${selectedProject.current_render.id}/file`}
                          download={`short_${selectedProject.id.slice(0, 8)}.mp4`}
                          style={{
                            padding: '0.5rem 0.85rem',
                            backgroundColor: 'var(--bg-card)',
                            border: '1px solid var(--border-color)',
                            borderRadius: '4px',
                            color: 'var(--text-primary)',
                            fontSize: '0.8125rem',
                            textDecoration: 'none',
                            fontWeight: 600
                          }}
                        >
                          ⬇ Download MP4
                        </a>

                        {selectedProject.status !== 'APPROVED' && (
                          <button
                            onClick={() => handleApproveRender(selectedProject.current_render.id)}
                            style={{
                              padding: '0.5rem 1rem',
                              backgroundColor: 'rgba(16, 185, 129, 0.2)',
                              border: '1px solid var(--accent-emerald)',
                              borderRadius: '4px',
                              color: '#6ee7b7',
                              fontWeight: 700,
                              fontSize: '0.8125rem'
                            }}
                          >
                            ✓ Approve Render (Locks Checksum)
                          </button>
                        )}

                        <button
                          onClick={() => handleRejectRender(selectedProject.current_render.id)}
                          style={{
                            padding: '0.5rem 0.85rem',
                            backgroundColor: 'rgba(244, 63, 94, 0.1)',
                            border: '1px solid var(--accent-rose)',
                            borderRadius: '4px',
                            color: '#fda4af',
                            fontWeight: 600,
                            fontSize: '0.8125rem'
                          }}
                        >
                          ✕ Reject
                        </button>
                      </div>
                      <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
                        * Approval is cryptographically bound to this render's SHA-256 checksum. Editing below supersedes approval.
                      </p>
                    </div>
                  </div>
                </div>
              ) : (
                <div style={{ padding: '1.25rem', backgroundColor: 'var(--bg-primary)', border: '1px dashed var(--border-color)', borderRadius: '6px', textAlign: 'center', color: 'var(--text-muted)', marginBottom: '1.5rem', fontSize: '0.875rem' }}>
                  No active render found. Click "Render 1080p" to produce an immutable vertical video.
                </div>
              )}

              {/* Stage 3: Editorial QA Review Card */}
              {selectedProject.editorial_review && (
                <div style={{
                  backgroundColor: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: '8px',
                  padding: '1.25rem',
                  marginBottom: '1.5rem'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#f59e0b' }}>
                      📋 Editorial Quality &amp; Retention Audit
                    </h3>
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>Score:</span>
                      <span style={{
                        padding: '0.2rem 0.6rem',
                        borderRadius: '4px',
                        fontSize: '0.8125rem',
                        fontWeight: 700,
                        backgroundColor: selectedProject.editorial_review.score >= 80 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)',
                        color: selectedProject.editorial_review.score >= 80 ? '#6ee7b7' : '#fcd34d'
                      }}>
                        {selectedProject.editorial_review.score}/100 ({selectedProject.editorial_review.overall_status})
                      </span>
                    </div>
                  </div>

                  {selectedProject.editorial_review.warnings && selectedProject.editorial_review.warnings.length > 0 ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                      {selectedProject.editorial_review.warnings.map((w, idx) => (
                        <div key={idx} style={{
                          fontSize: '0.8125rem',
                          padding: '0.5rem 0.75rem',
                          borderRadius: '4px',
                          backgroundColor: 'rgba(245, 158, 11, 0.1)',
                          borderLeft: '3px solid #f59e0b',
                          color: '#fde68a'
                        }}>
                          <strong>[{w.category}]</strong> {w.message}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p style={{ fontSize: '0.8125rem', color: '#6ee7b7', margin: 0 }}>
                      ✓ All editorial criteria passed: strong opening hook, balanced pacing, and verified claim relevance.
                    </p>
                  )}
                </div>
              )}

              {/* Stage 6: YouTube OAuth & Guarded Private Publishing Card */}
              <div style={{
                backgroundColor: 'var(--bg-primary)',
                border: '1px solid var(--border-color)',
                borderRadius: '8px',
                padding: '1.25rem',
                marginBottom: '1.5rem'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.85rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                    <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#ef4444', margin: 0 }}>
                      🔴 YouTube Publishing &amp; OAuth
                    </h3>
                    <span style={{
                      padding: '0.2rem 0.6rem',
                      borderRadius: '4px',
                      fontSize: '0.75rem',
                      fontWeight: 700,
                      backgroundColor: youtubeStatus?.connected ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.15)',
                      color: youtubeStatus?.connected ? '#6ee7b7' : '#fca5a5'
                    }}>
                      {youtubeStatus?.connected ? `Connected: ${youtubeStatus.channel_title || 'Channel'}` : 'Disconnected'}
                    </span>
                  </div>

                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    {!youtubeStatus?.client_configured && (
                      <button
                        onClick={() => setShowConfigModal(true)}
                        style={{
                          padding: '0.4rem 0.8rem',
                          backgroundColor: 'rgba(59, 130, 246, 0.15)',
                          border: '1px solid #3b82f6',
                          borderRadius: '4px',
                          color: '#93c5fd',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          cursor: 'pointer'
                        }}
                      >
                        ⚙️ Configure Google Client
                      </button>
                    )}

                    {youtubeStatus?.client_configured && !youtubeStatus?.connected && (
                      <button
                        onClick={handleConnectYouTube}
                        style={{
                          padding: '0.4rem 0.8rem',
                          backgroundColor: '#ef4444',
                          border: 'none',
                          borderRadius: '4px',
                          color: '#fff',
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          cursor: 'pointer'
                        }}
                      >
                        🔑 Connect YouTube
                      </button>
                    )}

                    {youtubeStatus?.connected && (
                      <button
                        onClick={handleDisconnectYouTube}
                        style={{
                          padding: '0.4rem 0.8rem',
                          backgroundColor: 'rgba(239, 68, 68, 0.1)',
                          border: '1px solid #ef4444',
                          borderRadius: '4px',
                          color: '#fca5a5',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          cursor: 'pointer'
                        }}
                      >
                        Disconnect
                      </button>
                    )}
                  </div>
                </div>

                {/* Guarded Upload Controls */}
                {selectedProject.current_render && selectedProject.active_approval ? (
                  <div style={{
                    padding: '1rem',
                    backgroundColor: 'var(--bg-card)',
                    borderRadius: '6px',
                    border: '1px solid var(--border-color)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.85rem'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.8125rem', color: '#6ee7b7' }}>
                        🔒 <strong>Human Approval Active:</strong> Bound to checksum <code>{selectedProject.current_render.render_checksum.slice(0, 12)}...</code>
                      </span>
                      <span style={{
                        padding: '0.2rem 0.5rem',
                        borderRadius: '3px',
                        fontSize: '0.7rem',
                        fontWeight: 700,
                        backgroundColor: 'rgba(16, 185, 129, 0.15)',
                        color: '#6ee7b7'
                      }}>
                        READY FOR PRIVATE UPLOAD
                      </span>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                      <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Video Title (Max 100 chars):</label>
                      <input
                        type="text"
                        defaultValue={selectedProject.title}
                        onChange={(e) => setPublishTitle(e.target.value)}
                        style={{
                          padding: '0.5rem 0.75rem',
                          backgroundColor: 'var(--bg-primary)',
                          border: '1px solid var(--border-color)',
                          borderRadius: '4px',
                          color: 'var(--text-primary)',
                          fontSize: '0.8125rem'
                        }}
                      />

                      <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Description (Source attributions will be appended automatically):</label>
                      <textarea
                        defaultValue={selectedProject.topic}
                        onChange={(e) => setPublishDesc(e.target.value)}
                        rows={2}
                        style={{
                          padding: '0.5rem 0.75rem',
                          backgroundColor: 'var(--bg-primary)',
                          border: '1px solid var(--border-color)',
                          borderRadius: '4px',
                          color: 'var(--text-primary)',
                          fontSize: '0.8125rem',
                          resize: 'vertical'
                        }}
                      />
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.25rem' }}>
                      <div style={{ fontSize: '0.75rem', color: '#f59e0b', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <span>🔒</span> Initial uploads are strictly <strong>PRIVATE</strong> (Stage 6 Invariant). No automatic public release.
                      </div>

                      <button
                        onClick={handleUploadToYouTube}
                        disabled={publishLoading || !youtubeStatus?.connected}
                        style={{
                          padding: '0.6rem 1.25rem',
                          backgroundColor: !youtubeStatus?.connected ? '#64748b' : publishLoading ? '#94a3b8' : '#ef4444',
                          color: '#fff',
                          border: 'none',
                          borderRadius: '6px',
                          fontWeight: 700,
                          fontSize: '0.8125rem',
                          cursor: !youtubeStatus?.connected || publishLoading ? 'not-allowed' : 'pointer'
                        }}
                      >
                        {publishLoading ? '⏳ Uploading Privately...' : '🚀 Upload Private Short to YouTube'}
                      </button>
                    </div>

                    {publishResult && (
                      <div style={{
                        marginTop: '0.5rem',
                        padding: '0.75rem',
                        backgroundColor: 'rgba(16, 185, 129, 0.15)',
                        border: '1px solid #10b981',
                        borderRadius: '4px',
                        fontSize: '0.8125rem',
                        color: '#6ee7b7'
                      }}>
                        🎉 <strong>Upload Confirmed!</strong> Video ID: <code>{publishResult.video_id}</code> (Privacy: private)
                        <br />
                        <a
                          href={publishResult.youtube_url}
                          target="_blank"
                          rel="noreferrer"
                          style={{ color: '#38bdf8', textDecoration: 'underline', marginTop: '0.25rem', display: 'inline-block' }}
                        >
                          View Private Video on YouTube Studio ↗
                        </a>
                      </div>
                    )}

                    {publishError && (
                      <div style={{
                        marginTop: '0.5rem',
                        padding: '0.75rem',
                        backgroundColor: 'rgba(239, 68, 68, 0.15)',
                        border: '1px solid #ef4444',
                        borderRadius: '4px',
                        fontSize: '0.8125rem',
                        color: '#fca5a5'
                      }}>
                        ⚠️ <strong>Upload Failed:</strong> {publishError}
                      </div>
                    )}
                  </div>
                ) : (
                  <div style={{
                    padding: '0.85rem',
                    backgroundColor: 'rgba(245, 158, 11, 0.08)',
                    borderRadius: '6px',
                    border: '1px dashed #f59e0b',
                    fontSize: '0.8125rem',
                    color: '#fde68a'
                  }}>
                    ⚠️ <strong>Publishing Invariant:</strong> You must approve the active 1080p render above before private YouTube publishing is unlocked.
                  </div>
                )}
              </div>

              {/* Stage 3: Visual Asset Provenance & Attribution Ledger */}
              {selectedProject.asset_provenances && selectedProject.asset_provenances.length > 0 && (
                <div style={{
                  backgroundColor: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: '8px',
                  padding: '1.25rem',
                  marginBottom: '1.5rem'
                }}>
                  <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--accent-cyan)', marginBottom: '0.75rem' }}>
                    🎨 Visual Asset Provenance &amp; Attribution
                  </h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                    {selectedProject.asset_provenances.map((ap, idx) => (
                      <div key={idx} style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.25rem',
                        fontSize: '0.8125rem',
                        padding: '0.6rem 0.75rem',
                        backgroundColor: 'var(--bg-card)',
                        borderRadius: '4px',
                        border: '1px solid var(--border-color)'
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <div>
                            <span style={{
                              padding: '0.15rem 0.45rem',
                              borderRadius: '3px',
                              fontSize: '0.7rem',
                              fontWeight: 700,
                              marginRight: '0.4rem',
                              backgroundColor: ap.asset_type === 'NASA' ? 'rgba(59, 130, 246, 0.2)' :
                                ap.asset_type === 'WIKIMEDIA' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(168, 85, 247, 0.2)',
                              color: ap.asset_type === 'NASA' ? '#93c5fd' :
                                ap.asset_type === 'WIKIMEDIA' ? '#86efac' : '#d8b4fe'
                            }}>
                              {ap.asset_type}
                            </span>
                            <span style={{
                              padding: '0.15rem 0.4rem',
                              borderRadius: '3px',
                              fontSize: '0.68rem',
                              fontWeight: 600,
                              marginRight: '0.5rem',
                              backgroundColor: ap.media_type === 'video' ? 'rgba(239, 68, 68, 0.2)' : 'rgba(107, 114, 128, 0.2)',
                              color: ap.media_type === 'video' ? '#fca5a5' : '#d1d5db'
                            }}>
                              {ap.media_type === 'video' ? '🎬 VIDEO' : '🖼️ IMAGE'}
                            </span>
                            <strong style={{ color: 'var(--text-primary)' }}>Scene {ap.scene_index + 1}:</strong> {ap.attribution_text || ap.author || 'Generated Graphic'}
                          </div>
                          <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                            Rights: <strong style={{ color: ap.rights_status === 'PUBLIC_DOMAIN' ? '#86efac' : '#93c5fd' }}>{ap.rights_status || 'VERIFIED_FREE'}</strong>
                          </div>
                        </div>
                        {ap.selection_reason && (
                          <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontStyle: 'italic', paddingLeft: '0.25rem' }}>
                            Modality: {ap.selection_reason}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Editorial Validation & FactLedger Panel */}
              {(validationReport || (selectedProject.fact_claims && selectedProject.fact_claims.length > 0)) && (
                <div style={{ backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '1rem', marginBottom: '1.5rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--accent-cyan)' }}>
                      🔬 FactLedger &amp; Editorial Intelligence
                    </h3>
                    {validationReport && (
                      <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.75rem' }}>
                        <span>Cadence: <strong>{validationReport.lexical_density_wps} WPS</strong></span>
                        <span>Evidence Coverage: <strong>{Math.round(validationReport.claim_coverage_ratio * 100)}%</strong></span>
                      </div>
                    )}
                  </div>

                  {/* Validation Alerts */}
                  {validationReport?.errors?.length > 0 && (
                    <div style={{ padding: '0.5rem', backgroundColor: 'rgba(239, 68, 68, 0.15)', border: '1px solid var(--accent-rose)', borderRadius: '4px', marginBottom: '0.5rem', fontSize: '0.75rem', color: '#fca5a5' }}>
                      {validationReport.errors.map((e: any, i: number) => (
                        <div key={i}>⚠️ <strong>{e.rule}:</strong> {e.message}</div>
                      ))}
                    </div>
                  )}

                  {validationReport?.warnings?.length > 0 && (
                    <div style={{ padding: '0.5rem', backgroundColor: 'rgba(245, 158, 11, 0.1)', border: '1px solid #f59e0b', borderRadius: '4px', marginBottom: '0.75rem', fontSize: '0.75rem', color: '#fcd34d' }}>
                      {validationReport.warnings.map((w: any, i: number) => (
                        <div key={i}>ℹ️ <strong>{w.rule}:</strong> {w.message}</div>
                      ))}
                    </div>
                  )}

                  {/* Claims List */}
                  {selectedProject.fact_claims && selectedProject.fact_claims.length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                      <span style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600 }}>
                        Extracted Claims ({selectedProject.fact_claims.length}) · Sources ({selectedProject.fact_sources?.length || 0})
                      </span>
                      {selectedProject.fact_claims.map((claim, ci) => (
                        <div key={ci} style={{ padding: '0.5rem', backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '4px', fontSize: '0.75rem' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.25rem' }}>
                            <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{claim.claim_text}</span>
                            <span style={{
                              padding: '0.1rem 0.4rem',
                              borderRadius: '3px',
                              fontWeight: 700,
                              fontSize: '0.6875rem',
                              backgroundColor:
                                claim.evidence_status === 'VERIFIED' ? 'rgba(16, 185, 129, 0.2)' :
                                claim.evidence_status === 'INSUFFICIENT_EVIDENCE' ? 'rgba(239, 68, 68, 0.2)' : 'rgba(245, 158, 11, 0.2)',
                              color:
                                claim.evidence_status === 'VERIFIED' ? '#6ee7b7' :
                                claim.evidence_status === 'INSUFFICIENT_EVIDENCE' ? '#fca5a5' : '#fcd34d'
                            }}>
                              {claim.evidence_status}
                            </span>
                          </div>
                          {claim.quote_excerpt && (
                            <p style={{ color: 'var(--text-muted)', fontStyle: 'italic', margin: '0.2rem 0' }}>
                              &ldquo;{claim.quote_excerpt}&rdquo;
                            </p>
                          )}
                          <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontSize: '0.6875rem', marginTop: '0.2rem' }}>
                            {claim.source_url ? (
                              <a href={claim.source_url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent-cyan)', textDecoration: 'none' }}>
                                🔗 {claim.source_title || claim.source_url}
                              </a>
                            ) : <span>No direct source URL</span>}
                            {claim.uncertainty_rationale && <span style={{ color: '#fcd34d' }}>{claim.uncertainty_rationale}</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Storyboard Editor & Asset Ingest */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                  <h3 style={{ fontSize: '1rem', fontWeight: 600 }}>Storyboard Scenes &amp; Visual Assets</h3>
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                      onClick={handleOpenFlowPrompts}
                      style={{
                        padding: '0.4rem 0.85rem',
                        borderRadius: '4px',
                        backgroundColor: 'rgba(168, 85, 247, 0.2)',
                        border: '1px solid rgba(168, 85, 247, 0.5)',
                        color: '#d8b4fe',
                        fontWeight: 600,
                        fontSize: '0.8125rem',
                        cursor: 'pointer'
                      }}
                    >
                      ✨ Google Flow Prompts
                    </button>
                    <button
                      onClick={handleSaveStoryboard}
                      style={{
                        padding: '0.4rem 0.85rem',
                        borderRadius: '4px',
                        backgroundColor: 'var(--accent-cyan)',
                        border: 'none',
                        color: '#0b0f17',
                        fontWeight: 700,
                        fontSize: '0.8125rem',
                        cursor: 'pointer'
                      }}
                    >
                      Save Storyboard
                    </button>
                  </div>
                </div>

                {storyboardSavedMsg && (
                  <div style={{ padding: '0.5rem 0.75rem', backgroundColor: 'rgba(6, 182, 212, 0.15)', border: '1px solid var(--accent-cyan)', borderRadius: '4px', color: '#67e8f9', fontSize: '0.8125rem', marginBottom: '0.75rem' }}>
                    {storyboardSavedMsg}
                  </div>
                )}

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {editableScenes.map((scene, idx) => (
                    <div
                      key={idx}
                      style={{
                        backgroundColor: 'var(--bg-primary)',
                        border: '1px solid var(--border-color)',
                        borderRadius: '6px',
                        padding: '1rem'
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                        <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>
                          Scene {idx + 1}: {scene.scene_title}
                        </span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Duration (s):</label>
                          <input
                            type="number"
                            value={scene.duration_seconds}
                            step="0.5"
                            min="1"
                            max="30"
                            onChange={(e) => {
                              const updated = [...editableScenes];
                              updated[idx].duration_seconds = Number(e.target.value);
                              setEditableScenes(updated);
                            }}
                            style={{ width: '60px', padding: '0.2rem 0.4rem', backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '4px', color: '#fff', fontSize: '0.75rem' }}
                          />
                        </div>
                      </div>

                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '0.5rem' }}>
                        <div>
                          <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.2rem' }}>Narration Text</label>
                          <textarea
                            value={scene.narration_text}
                            rows={2}
                            onChange={(e) => {
                              const updated = [...editableScenes];
                              updated[idx].narration_text = e.target.value;
                              setEditableScenes(updated);
                            }}
                            style={{ width: '100%', padding: '0.4rem', backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '4px', color: '#fff', fontSize: '0.8125rem' }}
                          />
                        </div>

                        <div>
                          <label style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.2rem' }}>Burned Caption Text</label>
                          <textarea
                            value={scene.caption_text}
                            rows={2}
                            onChange={(e) => {
                              const updated = [...editableScenes];
                              updated[idx].caption_text = e.target.value;
                              setEditableScenes(updated);
                            }}
                            style={{ width: '100%', padding: '0.4rem', backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '4px', color: '#fff', fontSize: '0.8125rem' }}
                          />
                        </div>
                      </div>

                      {/* Visual Asset Ingest & Flow Video Import */}
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-muted)', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '0.5rem' }}>
                        <span>
                          Asset: {scene.visual_asset_path?.endsWith('.mp4') ? '🎥 Flow Video Linked' : scene.visual_asset_path ? '🖼️ Custom Image' : '🎨 Procedural Graphic'}
                        </span>
                        <div style={{ display: 'flex', gap: '0.75rem' }}>
                          <label style={{ cursor: 'pointer', color: '#c084fc', fontWeight: 600 }}>
                            📥 Import Flow Video (.mp4)
                            <input
                              type="file"
                              accept="video/mp4,video/webm,video/quicktime"
                              onChange={(e) => scene.id && handleImportFlowVideo(e, scene.id)}
                              style={{ display: 'none' }}
                            />
                          </label>
                          <label style={{ cursor: 'pointer', color: 'var(--accent-cyan)', fontWeight: 600 }}>
                            Replace Image
                            <input
                              type="file"
                              accept="image/png,image/jpeg"
                              onChange={(e) => handleFileUpload(e, scene.id, 'image')}
                              style={{ display: 'none' }}
                            />
                          </label>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Manual Narration Upload (if manual mode) */}
                {selectedProject.narration_mode === 'manual_audio' && (
                  <div style={{ marginTop: '1rem', padding: '0.75rem', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '6px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.8125rem' }}>
                        Voiceover Audio: {selectedProject.narration_audio_path ? 'Voiceover Linked' : 'No Audio File'}
                      </span>
                      <label style={{ cursor: 'pointer', color: 'var(--accent-emerald)', fontSize: '0.8125rem', fontWeight: 600 }}>
                        Upload Audio (WAV/MP3)
                        <input
                          type="file"
                          accept="audio/wav,audio/mpeg,audio/aac"
                          onChange={(e) => handleFileUpload(e, undefined, 'audio')}
                          style={{ display: 'none' }}
                        />
                      </label>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)' }}>
              Select a project from the sidebar or click "+ New Video Project" to begin.
            </div>
          )}
        </section>
      </section>

      {/* Worker Job Queue Table */}
      <section style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <div>
            <h2 style={{ fontSize: '1.125rem', fontWeight: 600 }}>Worker Job Queue</h2>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
              Single-worker slot · Database-backed lease &amp; heartbeat · Resource limits enforced
            </p>
          </div>
          <span style={{ fontSize: '0.8125rem', padding: '0.25rem 0.65rem', backgroundColor: 'var(--bg-secondary)', borderRadius: '4px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {jobs.length} jobs total
          </span>
        </div>

        {jobs.length === 0 ? (
          <div style={{ padding: '2.5rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.875rem' }}>
            No jobs in queue.
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
                    <td style={{ padding: '0.75rem 0.5rem', fontWeight: 600, color: 'var(--text-primary)' }}>{job.stage}</td>
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
                    <td style={{ padding: '0.75rem 0.5rem', fontFamily: 'var(--font-mono)' }}>{job.attempts} / {job.max_attempts}</td>
                    <td style={{ padding: '0.75rem 0.5rem', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{job.idempotency_key}</td>
                    <td style={{ padding: '0.75rem 0.5rem', color: 'var(--text-muted)', fontSize: '0.8125rem' }}>{new Date(job.created_at).toLocaleTimeString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {/* Modal: Google OAuth Client Configuration */}
      {showConfigModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.7)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000
        }}>
          <div style={{
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '10px',
            padding: '2rem',
            width: '100%',
            maxWidth: '520px',
            boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)'
          }}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
              ⚙️ Configure Google OAuth Web Client
            </h3>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginBottom: '1.25rem' }}>
              Stored with <code>0600</code> permissions in <code>data/secrets/client_secret.json</code> outside Git.
              Never embedded in code or logged.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginBottom: '1.5rem' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8125rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                  Google Client ID:
                </label>
                <input
                  type="text"
                  placeholder="e.g. 123456789-xyz.apps.googleusercontent.com"
                  value={clientIdInput}
                  onChange={(e) => setClientIdInput(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '0.6rem 0.75rem',
                    backgroundColor: 'var(--bg-primary)',
                    border: '1px solid var(--border-color)',
                    borderRadius: '6px',
                    color: 'var(--text-primary)',
                    fontSize: '0.8125rem'
                  }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8125rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                  Google Client Secret:
                </label>
                <input
                  type="password"
                  placeholder="e.g. GOCSPX-xxxxxxxxxxxxxxxx"
                  value={clientSecretInput}
                  onChange={(e) => setClientSecretInput(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '0.6rem 0.75rem',
                    backgroundColor: 'var(--bg-primary)',
                    border: '1px solid var(--border-color)',
                    borderRadius: '6px',
                    color: 'var(--text-primary)',
                    fontSize: '0.8125rem'
                  }}
                />
              </div>

              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                <strong>Redirect URI configured in Google Cloud:</strong><br />
                <code style={{ color: '#38bdf8' }}>http://localhost:8000/api/v1/auth/youtube/callback</code>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
              <button
                onClick={() => setShowConfigModal(false)}
                style={{
                  padding: '0.5rem 1rem',
                  backgroundColor: 'transparent',
                  border: '1px solid var(--border-color)',
                  borderRadius: '6px',
                  color: 'var(--text-muted)',
                  fontSize: '0.8125rem',
                  cursor: 'pointer'
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleConfigureYouTube}
                style={{
                  padding: '0.5rem 1.25rem',
                  backgroundColor: '#3b82f6',
                  border: 'none',
                  borderRadius: '6px',
                  color: '#fff',
                  fontWeight: 600,
                  fontSize: '0.8125rem',
                  cursor: 'pointer'
                }}
              >
                Save Credentials
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Google Flow Prompt Packages (Track 1) */}
      {showFlowModal && flowManifest && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.75)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000
        }}>
          <div style={{
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '10px',
            padding: '1.75rem',
            width: '100%',
            maxWidth: '750px',
            maxHeight: '90vh',
            overflowY: 'auto',
            boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
              <h3 style={{ fontSize: '1.125rem', fontWeight: 600, color: '#d8b4fe' }}>
                ✨ Google Flow Prompt Packages (Jio AI Pro)
              </h3>
              <button
                onClick={() => setShowFlowModal(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: '1.25rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            <div style={{ padding: '0.75rem', backgroundColor: 'rgba(168, 85, 247, 0.1)', border: '1px solid rgba(168, 85, 247, 0.3)', borderRadius: '6px', marginBottom: '1rem', fontSize: '0.8125rem', color: '#e9d5ff' }}>
              💡 <strong>Handoff Notice:</strong> In Google Flow (<code>labs.google/flow</code>), set Aspect Ratio to <strong>9:16</strong> (Portrait) and choose 4s or 8s duration. UI controls are selected manually in the browser. After generation, download the MP4 and import it below or place it in <code>data/inbox/</code>.
            </div>

            {flowCopyNotice && (
              <div style={{ padding: '0.5rem', backgroundColor: 'rgba(16, 185, 129, 0.2)', border: '1px solid #10b981', borderRadius: '4px', color: '#6ee7b7', fontSize: '0.8125rem', marginBottom: '1rem', textAlign: 'center' }}>
                ✓ {flowCopyNotice}
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginBottom: '1.5rem' }}>
              {flowManifest.scenes?.map((pkg: any, idx: number) => (
                <div key={idx} style={{ backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '6px', padding: '1rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <span style={{ fontWeight: 600, fontSize: '0.875rem', color: '#fff' }}>
                      Scene {idx + 1}: {pkg.scene_title} ({pkg.requested_duration} · {pkg.aspect_ratio})
                    </span>
                    <button
                      onClick={() => handleCopyFlowPrompt(pkg.exact_prompt, idx)}
                      style={{
                        padding: '0.3rem 0.75rem',
                        backgroundColor: '#9333ea',
                        border: 'none',
                        borderRadius: '4px',
                        color: '#fff',
                        fontWeight: 600,
                        fontSize: '0.75rem',
                        cursor: 'pointer'
                      }}
                    >
                      📋 Copy Prompt
                    </button>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
                    <strong>Narrative Beat:</strong> {pkg.narrative_intent}
                  </div>
                  <div style={{ padding: '0.6rem', backgroundColor: '#0f172a', borderRadius: '4px', fontSize: '0.8125rem', color: '#cbd5e1', fontFamily: 'monospace', lineHeight: 1.4, marginBottom: '0.5rem' }}>
                    {pkg.exact_prompt}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: '#ef4444' }}>
                    <strong>Negative:</strong> {pkg.forbidden_artifacts}
                  </div>
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setShowFlowModal(false)}
                style={{
                  padding: '0.5rem 1.25rem',
                  backgroundColor: 'var(--border-color)',
                  border: 'none',
                  borderRadius: '6px',
                  color: '#fff',
                  fontSize: '0.8125rem',
                  cursor: 'pointer'
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
