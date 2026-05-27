import { type ChangeEvent, type KeyboardEvent, type RefObject, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE_URL = "http://127.0.0.1:8000/api";
const SEGMENT_TYPES = ["噱头引入", "痛点", "产品方案", "效果展示", "信任背书", "价格对比", "活动福利", "行动号召", "产品定位", "过渡"];
const POSITION_TYPES = ["开头", "中间", "结尾"];
const SIDEBAR_CATEGORY_LIMIT = 4;
const SCHEME_PREVIEW_START_GUARD_SECONDS = 0.06;
const SCHEME_PREVIEW_END_GUARD_SECONDS = 0.02;

type WorkspaceView = "workspace" | "overview" | "import" | "assets" | "scripts" | "voice" | "materialMix" | "schemes" | "subtitles" | "settings";

type Project = {
  id: number;
  name: string;
  category: string;
  custom_prompt: string;
  custom_tags: string;
  status: string;
  video_count: number;
  segment_count: number;
  scheme_count: number;
  updated_at?: string;
};

type VideoItem = {
  id: number;
  project_id: number;
  name: string;
  local_path: string;
  thumbnail_path: string;
  duration_seconds: number;
  width: number;
  height: number;
  fps: number;
  asset_type?: string;
  source_mode?: string;
  has_voice?: number;
  has_bgm?: number;
  has_captions?: number;
  keep_original_audio?: number;
  transcript: string;
  transcript_segments?: string;
  status: string;
  error_message: string;
};

type Segment = {
  id: number;
  project_id: number;
  video_id: number;
  video_name: string;
  start_seconds: number;
  end_seconds: number;
  text: string;
  semantic_type: string;
  position_type: string;
  visual_description?: string;
  selling_points?: string;
  visual_tags?: string;
  source_mode?: string;
  keep_original_audio?: number | boolean;
};

type Asset = {
  id: number;
  project_id?: number;
  asset_type: string;
  name: string;
  file_path: string;
  tags: string;
  duration_seconds: number;
  status: string;
  metadata?: Record<string, unknown>;
};

type ScriptLine = {
  line_index: number;
  text: string;
  semantic_type: string;
  selling_points: string[];
  visual_needs: string[];
  estimated_duration: number;
};

type ScriptDraft = {
  id: number;
  project_id: number;
  title: string;
  source_type: string;
  source_text: string;
  product_context: string;
  lines: ScriptLine[];
  created_at: string;
};

type AiTask = {
  id: number;
  project_id?: number;
  task_type: string;
  target_type: string;
  target_id: number;
  status: string;
  message: string;
  metadata?: Record<string, unknown>;
  updated_at?: string;
};

type SubtitleStyleDraft = {
  font: string;
  size: number;
  primary_color: string;
  outline_color: string;
  back_color: string;
  bold: boolean;
  outline: number;
  shadow: number;
  alignment: number;
  margin_v: number;
};

type TranscriptSegment = {
  start_seconds: number;
  end_seconds: number;
  text: string;
};

type Scheme = {
  id: number;
  strategy_id?: number;
  name: string;
  scheme_description: string;
  estimated_duration: number;
  actual_duration?: number;
  segment_count?: number;
  repeat_rate?: number;
  recommendation_score?: number;
  is_recommended?: boolean;
  style: string;
  target_audience: string;
  narrative_structure: string;
  differentiation: string;
  strategy_reasoning?: string;
  segments?: SchemeSegment[];
};

type SchemeSegment = Segment & {
  scheme_segment_id: number;
  position: number;
  reasoning: string;
  position_reasoning: string;
};

type MaterialMixClip = {
  clip_id: number;
  timeline_id: number;
  segment_id: number;
  source_path: string;
  source_in: number;
  source_out: number;
  timeline_in: number;
  timeline_out: number;
  track_type: "video";
  position: number;
  text: string;
  semantic_type: string;
  position_type: string;
  selling_points?: string;
  visual_tags?: string;
  visual_description?: string;
  video_name: string;
  generation_note?: string;
  selection_note?: string;
};

type MaterialMixTimeline = {
  id: number;
  timeline_id: number;
  project_id: number;
  name: string;
  duration_seconds: number;
  clip_count: number;
  is_favorite?: number | boolean;
  voice_asset_id?: number;
  bgm_asset_id?: number;
  subtitle_preset_id?: number;
  audio_policy?: string;
  normalize_loudness?: number | boolean;
  target_lufs?: number;
  burn_subtitles?: number | boolean;
  updated_at?: string;
  clips?: MaterialMixClip[];
  generation_warnings?: string[];
  generation_notes?: Record<string, string>;
};

type Settings = Record<string, string>;

type ElectronAPI = {
  selectExportDirectory?: () => Promise<string | null>;
};

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail ?? "请求失败");
  }
  return data as T;
}

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<number | null>(null);
  const [view, setView] = useState<WorkspaceView>("overview");
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [schemes, setSchemes] = useState<Scheme[]>([]);
  const [selectedScheme, setSelectedScheme] = useState<Scheme | null>(null);
  const [settings, setSettings] = useState<Settings>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [newProjectName, setNewProjectName] = useState("新混剪项目");
  const [newProjectCategory, setNewProjectCategory] = useState("默认");
  const [projectCategoryFilter, setProjectCategoryFilter] = useState("");
  const [projectSearch, setProjectSearch] = useState("");

  const activeProject = useMemo(
    () => projects.find((project) => project.id === activeProjectId) ?? null,
    [activeProjectId, projects],
  );
  const projectCategories = useMemo(() => {
    const values = Array.from(new Set(projects.map((project) => project.category || "默认")));
    return values.sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  }, [projects]);
  const visibleProjects = useMemo(
    () => projects.filter((project) => !projectCategoryFilter || (project.category || "默认") === projectCategoryFilter),
    [projects, projectCategoryFilter],
  );
  const workspaceProjects = useMemo(
    () => visibleProjects.filter((project) => !projectSearch.trim() || `${project.name} ${project.category}`.toLowerCase().includes(projectSearch.trim().toLowerCase())),
    [projectSearch, visibleProjects],
  );
  const sidebarCategories = projectCategories.slice(0, SIDEBAR_CATEGORY_LIMIT);
  const overflowCategories = projectCategories.slice(SIDEBAR_CATEGORY_LIMIT);
  const overflowCategorySelected = Boolean(projectCategoryFilter && overflowCategories.includes(projectCategoryFilter));

  useEffect(() => {
    void loadProjects();
    void loadSettings();
  }, []);

  useEffect(() => {
    if (!message) return;
    const timer = window.setTimeout(() => setMessage(""), 3200);
    return () => window.clearTimeout(timer);
  }, [message]);

  useEffect(() => {
    if (!error) return;
    const timer = window.setTimeout(() => setError(""), 5200);
    return () => window.clearTimeout(timer);
  }, [error]);

  useEffect(() => {
    if (activeProject && view !== "workspace" && view !== "settings") {
      void loadProjectData(activeProject.id);
      return;
    }
    if (!activeProject) {
      setVideos([]);
      setSegments([]);
      setSchemes([]);
      setSelectedScheme(null);
    }
  }, [activeProject?.id, view]);

  useEffect(() => {
    if (!activeProject) {
      return;
    }
    const hasRunningVideos = videos.some((video) => ["imported", "transcribing", "transcribed", "segmenting"].includes(video.status));
    if (!hasRunningVideos) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadProjectData(activeProject.id);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activeProject?.id, videos]);

  async function loadProjects() {
    try {
      const data = await api<Project[]>("/projects");
      setProjects(data);
      setActiveProjectId((current) => (current && data.some((project) => project.id === current) ? current : null));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? `后端服务未连接：${err.message}` : "后端服务未连接");
    }
  }

  async function loadSettings() {
    try {
      setSettings(await api<Settings>("/settings"));
    } catch (err) {
      setError(err instanceof Error ? `设置加载失败：${err.message}` : "设置加载失败");
    }
  }

  async function loadProjectData(projectId: number) {
    setError("");
    try {
      const [videoData, segmentData, schemeData] = await Promise.all([
        api<VideoItem[]>(`/projects/${projectId}/videos`),
        api<Segment[]>(`/projects/${projectId}/segments`),
        api<Scheme[]>(`/projects/${projectId}/schemes`),
      ]);
      setVideos(videoData);
      setSegments(segmentData);
      setSchemes(schemeData);
      if (selectedScheme && !schemeData.some((scheme) => scheme.id === selectedScheme.id)) {
        setSelectedScheme(null);
      }
      await loadProjects();
    } catch (err) {
      setError(err instanceof Error ? err.message : "未知错误");
    }
  }

  async function createProject() {
    const name = newProjectName.trim();
    if (!name) {
      setError("请先填写项目名称。");
      return;
    }
    try {
      const project = await api<Project>("/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, custom_prompt: "", category: newProjectCategory.trim() || "默认" }),
      });
      setActiveProjectId(project.id);
      setView("overview");
      setNewProjectName("新混剪项目");
      setNewProjectCategory(project.category || "默认");
      await loadProjects();
      setMessage("项目已创建。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "项目创建失败");
    }
  }

  async function updateProject(project: Project, values: Partial<Pick<Project, "name" | "category" | "custom_prompt">>) {
    try {
      const payload = {
        ...values,
        category: values.category === undefined ? undefined : values.category.trim() || "默认",
        name: values.name === undefined ? undefined : values.name.trim(),
      };
      await api<Project>(`/projects/${project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      await loadProjects();
      setMessage("项目已更新。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "项目更新失败");
    }
  }

  async function deleteProject(project: Project) {
    if (!window.confirm(`确定删除项目「${project.name}」吗？项目内视频记录、片段和方案都会移除。`)) {
      return;
    }
    try {
      await api<{ deleted: boolean }>(`/projects/${project.id}`, { method: "DELETE" });
      if (activeProjectId === project.id) {
        setActiveProjectId(null);
        setView("workspace");
        setSelectedScheme(null);
        setVideos([]);
        setSegments([]);
        setSchemes([]);
      }
      await loadProjects();
      setMessage("项目已删除。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "项目删除失败");
    }
  }

  return (
    <main className="studio-shell">
      <aside className="project-sidebar">
        <div className="brand-block">
          <strong>AI Video Studio</strong>
          <button onClick={() => {
            setActiveProjectId(null);
            setView("workspace");
          }}>
            项目工作台
          </button>
          <button onClick={() => {
            setActiveProjectId(null);
            setView("workspace");
            window.setTimeout(() => document.getElementById("new-project-name")?.focus(), 0);
          }}>
            新建项目
          </button>
        </div>
        <div className="category-filter">
          <span>商品筛选</span>
          <button className={!projectCategoryFilter ? "active" : ""} onClick={() => setProjectCategoryFilter("")}>全部</button>
          {sidebarCategories.map((category) => (
            <button className={projectCategoryFilter === category ? "active" : ""} key={category} onClick={() => setProjectCategoryFilter(category)}>
              {category}
            </button>
          ))}
          {overflowCategories.length > 0 && (
            <select
              className={overflowCategorySelected ? "active" : ""}
              value={overflowCategorySelected ? projectCategoryFilter : ""}
              onChange={(event) => setProjectCategoryFilter(event.target.value)}
            >
              <option value="">更多商品</option>
              {overflowCategories.map((category) => <option key={category}>{category}</option>)}
            </select>
          )}
        </div>
        <div className="project-list">
          {visibleProjects.map((project) => (
            <article
              className={project.id === activeProject?.id ? "project-card active" : "project-card"}
              key={project.id}
            >
              <button
                className="project-open"
                onClick={() => {
                  setActiveProjectId(project.id);
                  setView("overview");
                  setSelectedScheme(null);
                }}
              >
                <span>{project.name}</span>
                <small>{project.category || "默认"} · {project.video_count} 视频 · {project.segment_count} 片段 · {project.scheme_count} 方案</small>
              </button>
            </article>
          ))}
          {projects.length === 0 && <p className="empty">先新建一个项目。</p>}
          {projects.length > 0 && visibleProjects.length === 0 && <p className="empty">这个商品下暂无项目。</p>}
        </div>
        <button className={view === "settings" ? "nav-item sidebar-settings active" : "nav-item sidebar-settings"} onClick={() => setView("settings")}>
          <span aria-hidden="true">⚙</span>
          <span>设置</span>
        </button>
      </aside>

      <section className="studio-main">
        {(message || error) && (
          <div className="toast-stack" role="status" aria-live="polite">
            {message && (
              <button className="app-toast success" onClick={() => setMessage("")}>
                {message}
              </button>
            )}
            {error && (
              <button className="app-toast error-toast" onClick={() => setError("")}>
                {error}
              </button>
            )}
          </div>
        )}

        {view === "settings" ? (
          <SettingsView settings={settings} onSaved={loadSettings} setMessage={setMessage} setError={setError} />
        ) : view === "workspace" || !activeProject ? (
          <ProjectWorkspace
            projects={workspaceProjects}
            allProjects={projects}
            categories={projectCategories}
            categoryFilter={projectCategoryFilter}
            setCategoryFilter={setProjectCategoryFilter}
            search={projectSearch}
            setSearch={setProjectSearch}
            newProjectName={newProjectName}
            setNewProjectName={setNewProjectName}
            newProjectCategory={newProjectCategory}
            setNewProjectCategory={setNewProjectCategory}
            onCreateProject={createProject}
            onDeleteProject={deleteProject}
            onUpdateProject={updateProject}
            onEnterProject={(project) => {
              setActiveProjectId(project.id);
              setView("overview");
              setSelectedScheme(null);
            }}
          />
        ) : activeProject ? (
          <>
            <ProjectHeader project={activeProject} view={view} setView={setView} />
            {view === "overview" && <Overview project={activeProject} videos={videos} segments={segments} schemes={schemes} />}
            {view === "import" && (
              <ImportAnalyze
                project={activeProject}
                videos={videos}
                segments={segments}
                onRefresh={() => loadProjectData(activeProject.id)}
                setMessage={setMessage}
                setError={setError}
              />
            )}
            {view === "assets" && <AssetWorkspace project={activeProject} segments={segments} videos={videos} onRefresh={() => loadProjectData(activeProject.id)} setError={setError} setMessage={setMessage} />}
            {view === "scripts" && <ScriptWorkspace project={activeProject} setError={setError} setMessage={setMessage} />}
            {view === "voice" && <VoiceWorkspace project={activeProject} setError={setError} setMessage={setMessage} />}
            {view === "materialMix" && (
              <MaterialMixWorkspace
                project={activeProject}
                segments={segments}
                setMessage={setMessage}
                setError={setError}
              />
            )}
            {view === "subtitles" && <SubtitleWorkspace project={activeProject} setError={setError} setMessage={setMessage} />}
            {view === "schemes" && (
              <SchemeWorkspace
                project={activeProject}
                segments={segments}
                schemes={schemes}
                selectedScheme={selectedScheme}
                setSelectedScheme={setSelectedScheme}
                onRefresh={() => loadProjectData(activeProject.id)}
                setMessage={setMessage}
                setError={setError}
              />
            )}
          </>
        ) : null}
      </section>
    </main>
  );
}

function ProjectWorkspace(props: {
  projects: Project[];
  allProjects: Project[];
  categories: string[];
  categoryFilter: string;
  setCategoryFilter: (value: string) => void;
  search: string;
  setSearch: (value: string) => void;
  newProjectName: string;
  setNewProjectName: (value: string) => void;
  newProjectCategory: string;
  setNewProjectCategory: (value: string) => void;
  onCreateProject: () => Promise<void>;
  onDeleteProject: (project: Project) => Promise<void>;
  onUpdateProject: (project: Project, values: Partial<Pick<Project, "name" | "category" | "custom_prompt">>) => Promise<void>;
  onEnterProject: (project: Project) => void;
}) {
  const [editingProjectId, setEditingProjectId] = useState<number | null>(null);
  const [editingName, setEditingName] = useState("");
  const [editingCategory, setEditingCategory] = useState("");

  function startEditing(project: Project) {
    setEditingProjectId(project.id);
    setEditingName(project.name);
    setEditingCategory(project.category || "默认");
  }

  async function saveEditing(project: Project) {
    await props.onUpdateProject(project, { name: editingName, category: editingCategory });
    setEditingProjectId(null);
  }

  return (
    <section className="project-workspace">
      <div className="workspace-sticky-head">
        <header className="project-workspace-header">
          <div>
            <h1>项目工作台</h1>
            <p>按商品管理项目，进入项目后再导入、分析和生成混剪方案。</p>
          </div>
          <div className="workspace-summary">
            <span>{props.allProjects.length} 项目</span>
            <span>{props.categories.length} 商品</span>
          </div>
        </header>

        <section className="panel project-create-panel">
          <label>项目名
            <input
              id="new-project-name"
              value={props.newProjectName}
              onChange={(event) => props.setNewProjectName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void props.onCreateProject();
                }
              }}
              placeholder="例如：618种草混剪"
            />
          </label>
          <label>商品名
            <input
              value={props.newProjectCategory}
              onChange={(event) => props.setNewProjectCategory(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void props.onCreateProject();
                }
              }}
              placeholder="例如：游戏玩家礼盒"
            />
          </label>
          <button className="primary-action" onClick={props.onCreateProject}>新建项目</button>
        </section>

        <section className="project-workspace-controls">
          <input value={props.search} onChange={(event) => props.setSearch(event.target.value)} placeholder="搜索项目或商品名..." />
          <select value={props.categoryFilter} onChange={(event) => props.setCategoryFilter(event.target.value)}>
            <option value="">全部商品</option>
            {props.categories.map((category) => <option key={category}>{category}</option>)}
          </select>
        </section>
      </div>

      <section className="project-workspace-list">
        {props.projects.map((project) => {
          const isEditing = editingProjectId === project.id;
          return (
            <article className="workspace-project-card" key={project.id}>
              <div className="workspace-project-main">
                {isEditing ? (
                  <div className="project-edit-fields">
                    <label>项目名
                      <input value={editingName} onChange={(event) => setEditingName(event.target.value)} />
                    </label>
                    <label>商品名
                      <input value={editingCategory} onChange={(event) => setEditingCategory(event.target.value)} />
                    </label>
                  </div>
                ) : (
                  <>
                    <div className="project-title-line">
                      <h2>{project.name}</h2>
                      <span>{project.category || "默认"}</span>
                    </div>
                    <p>{project.video_count} 视频 · {project.segment_count} 片段 · {project.scheme_count} 方案</p>
                    <small>最近更新 {formatProjectDate(project.updated_at)}</small>
                  </>
                )}
              </div>
              <div className="workspace-project-actions">
                {isEditing ? (
                  <>
                    <button className="primary-action" onClick={() => saveEditing(project)}>保存</button>
                    <button className="secondary" onClick={() => setEditingProjectId(null)}>取消</button>
                  </>
                ) : (
                  <>
                    <button className="primary-action" onClick={() => props.onEnterProject(project)}>进入项目</button>
                    <button className="secondary" onClick={() => startEditing(project)}>重命名/改商品</button>
                    <button className="danger-action" onClick={() => props.onDeleteProject(project)}>删除</button>
                  </>
                )}
              </div>
            </article>
          );
        })}
        {props.allProjects.length === 0 && (
          <section className="empty-state panel">
            <h2>还没有项目</h2>
            <p>先填写项目名和商品名，创建后开始导入视频。</p>
          </section>
        )}
        {props.allProjects.length > 0 && props.projects.length === 0 && <p className="empty panel">没有符合条件的项目。</p>}
      </section>
    </section>
  );
}

function formatProjectDate(value?: string) {
  if (!value) return "暂无";
  return value.replace("T", " ").slice(0, 16);
}

function ProjectHeader(props: { project: Project; view: WorkspaceView; setView: (view: WorkspaceView) => void }) {
  const tabs: Array<[WorkspaceView, string]> = [
    ["overview", "概览"],
    ["import", "导入分析"],
    ["assets", "素材库"],
    ["scripts", "文案中心"],
    ["voice", "配音/BGM"],
    ["materialMix", "素材混剪"],
    ["schemes", "混剪方案"],
    ["subtitles", "字幕模板"],
  ];
  return (
    <header className="project-header">
      <div>
        <h1>{props.project.name}</h1>
        <p>按项目工作台流程管理视频、语义片段和混剪方案。</p>
      </div>
      <nav className="workspace-tabs">
        {tabs.map(([value, label]) => (
          <button className={props.view === value ? "active" : ""} key={value} onClick={() => props.setView(value)}>
            {label}
          </button>
        ))}
      </nav>
    </header>
  );
}

function Overview(props: { project: Project; videos: VideoItem[]; segments: Segment[]; schemes: Scheme[] }) {
  const [previewVideo, setPreviewVideo] = useState<VideoItem | null>(null);
  return (
    <>
      <section className="overview-grid">
        <MetricCard label="视频" value={props.videos.length} />
        <MetricCard label="语义片段" value={props.segments.length} />
        <MetricCard label="混剪方案" value={props.schemes.length} />
        <div className="panel overview-panel">
          <h2>最近视频</h2>
          {props.videos.slice(0, 5).map((video) => (
            <button className="compact-row overview-video-row" key={video.id} onClick={() => setPreviewVideo(video)}>
              <span>{video.name}</span>
              <strong>{statusLabel(video.status)}</strong>
            </button>
          ))}
          {props.videos.length === 0 && <p className="empty">还没有导入视频。</p>}
        </div>
      </section>
      {previewVideo && (
        <div className="modal-backdrop" onClick={() => setPreviewVideo(null)}>
          <section className="video-preview-dialog" onClick={(event) => event.stopPropagation()}>
            <div className="split-head">
              <div>
                <h2>{previewVideo.name}</h2>
                <p>{previewVideo.width}x{previewVideo.height} · {previewVideo.duration_seconds.toFixed(1)}s · {statusLabel(previewVideo.status)}</p>
              </div>
              <button className="secondary" onClick={() => setPreviewVideo(null)}>关闭</button>
            </div>
            <video
              src={`${API_BASE_URL}/videos/${previewVideo.id}/preview`}
              poster={`${API_BASE_URL}/videos/${previewVideo.id}/thumbnail`}
              controls
              autoPlay
            />
          </section>
        </div>
      )}
    </>
  );
}

function MetricCard(props: { label: string; value: number }) {
  return (
    <div className="metric-card">
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </div>
  );
}

function ImportAnalyze(props: {
  project: Project;
  videos: VideoItem[];
  segments: Segment[];
  onRefresh: () => void;
  setMessage: (value: string) => void;
  setError: (value: string) => void;
}) {
  const finishedFileInputRef = useRef<HTMLInputElement | null>(null);
  const looseFileInputRef = useRef<HTMLInputElement | null>(null);
  const [customTagDraft, setCustomTagDraft] = useState(props.project.custom_tags ?? "");
  const [showBgmDialog, setShowBgmDialog] = useState(false);
  const [selectedBgmVideoIds, setSelectedBgmVideoIds] = useState<number[]>([]);
  const [importing, setImporting] = useState(false);
  const [assetImporting, setAssetImporting] = useState(false);
  const [batchTaggingBusy, setBatchTaggingBusy] = useState(false);
  const [finishedBatchBusy, setFinishedBatchBusy] = useState(false);
  const [taggingSegmentId, setTaggingSegmentId] = useState<number | null>(null);
  const [reanalyzingId, setReanalyzingId] = useState<number | null>(null);
  const productSegments = props.segments.filter((segment) => segment.source_mode === "product_assets" || !segment.text);
  const finishedVideos = props.videos.filter((video) => video.asset_type === "finished_video" || !video.asset_type);

  useEffect(() => {
    setCustomTagDraft(props.project.custom_tags ?? "");
  }, [props.project.id, props.project.custom_tags]);

  async function uploadVideo(selectedFiles: File[]) {
    if (selectedFiles.length === 0) {
      props.setError("请先选择一个或多个视频。");
      return;
    }
    const formData = new FormData();
    selectedFiles.forEach((file) => formData.append("files", file));
    setImporting(true);
    try {
      const imported = await fetch(`${API_BASE_URL}/projects/${props.project.id}/videos/import`, { method: "POST", body: formData }).then(async (response) => {
        if (!response.ok) throw new Error((await response.json()).detail ?? "导入失败");
        return response.json() as Promise<VideoItem[]>;
      });
      props.setMessage(`已导入 ${selectedFiles.length} 个成片，后台正在自动转录和切分。`);
      props.onRefresh();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "未知错误");
    } finally {
      setImporting(false);
    }
  }

  function openFinishedFilePicker() {
    finishedFileInputRef.current?.click();
  }

  function handleFinishedFilesSelected(event: ChangeEvent<HTMLInputElement>) {
    const selectedFiles = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (selectedFiles.length > 0) {
      void uploadVideo(selectedFiles);
    }
  }

  async function reanalyzeVideo(videoId: number) {
    setReanalyzingId(videoId);
    try {
      await api<VideoItem>(`/videos/${videoId}/reanalyze`, { method: "POST" });
      props.setMessage("已开始重新分析，会优先使用 ASR 时间戳生成更准确的片段。");
      props.onRefresh();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "重新分析失败");
    } finally {
      setReanalyzingId(null);
    }
  }

  async function reanalyzeFinishedBatch() {
    if (finishedVideos.length === 0) {
      props.setError("还没有可重新分析的成片。");
      return;
    }
    setFinishedBatchBusy(true);
    try {
      await Promise.all(finishedVideos.map((video) => api<VideoItem>(`/videos/${video.id}/reanalyze`, { method: "POST" })));
      props.setMessage(`已为 ${finishedVideos.length} 个成片重新创建分析任务。`);
      props.onRefresh();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "成片批量重新分析失败");
    } finally {
      setFinishedBatchBusy(false);
    }
  }

  async function uploadLooseAssets(selectedFiles: File[]) {
    if (selectedFiles.length === 0) {
      props.setError("请先选择零散素材文件。");
      return;
    }
    const formData = new FormData();
    selectedFiles.forEach((file) => formData.append("files", file));
    setAssetImporting(true);
    try {
      await fetch(`${API_BASE_URL}/projects/${props.project.id}/assets/import?asset_type=product_shot`, { method: "POST", body: formData }).then(async (response) => {
        if (!response.ok) throw new Error((await response.json()).detail ?? "导入失败");
      });
      if (customTagDraft.trim() !== (props.project.custom_tags ?? "").trim()) {
        await saveCustomTags(false);
      }
      const result = await api<{ analyzed_count: number; error_count: number }>("/projects/" + props.project.id + "/segments/analyze-visual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: Math.max(20, selectedFiles.length), only_missing: true }),
      });
      props.setMessage(`零散素材已导入并自动分析 ${result.analyzed_count} 个镜头${result.error_count ? `，${result.error_count} 个失败` : ""}。`);
      props.onRefresh();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "零散素材导入失败");
    } finally {
      setAssetImporting(false);
    }
  }

  function openLooseFilePicker() {
    const hasTag = customTagDraft.trim().length > 0 || String(props.project.custom_tags ?? "").trim().length > 0;
    if (!hasTag) {
      const shouldContinue = window.confirm("建议先录入产品卖点/画面 tag，AI 识别会更精准。仍然继续导入吗？");
      if (!shouldContinue) return;
    }
    looseFileInputRef.current?.click();
  }

  function handleLooseFilesSelected(event: ChangeEvent<HTMLInputElement>) {
    const selectedFiles = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (selectedFiles.length > 0) {
      void uploadLooseAssets(selectedFiles);
    }
  }

  async function analyzeVisual(segmentId: number) {
    setTaggingSegmentId(segmentId);
    try {
      await api(`/segments/${segmentId}/analyze-visual`, { method: "POST" });
      props.setMessage("已生成产品镜头卖点 tag。");
      props.onRefresh();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "视觉打标失败");
    } finally {
      setTaggingSegmentId(null);
    }
  }

  async function analyzeProductBatch() {
    setBatchTaggingBusy(true);
    try {
      const result = await api<{ analyzed_count: number; error_count: number }>("/projects/" + props.project.id + "/segments/analyze-visual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: 20, only_missing: true }),
      });
      props.setMessage(`已批量分析 ${result.analyzed_count} 个产品镜头${result.error_count ? `，${result.error_count} 个失败` : ""}。`);
      props.onRefresh();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "批量视觉打标失败");
    } finally {
      setBatchTaggingBusy(false);
    }
  }

  async function saveCustomTags(showMessage = true) {
    try {
      await api<Project>(`/projects/${props.project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ custom_tags: customTagDraft }),
      });
      if (showMessage) {
        props.setMessage("自定义 AI 打标 tag 已保存，后续 AI 打标会优先使用这些 tag。");
      }
      props.onRefresh();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "自定义 tag 保存失败");
    }
  }

  async function requestRemoveBgm(videoId: number, showMessage = true) {
    try {
      const result = await api<{ message: string }>("/audio/remove-bgm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_id: videoId }),
      });
      if (showMessage) {
        props.setMessage(result.message);
      }
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "去 BGM 任务创建失败");
    }
  }

  function toggleBgmVideo(videoId: number) {
    setSelectedBgmVideoIds((current) => (
      current.includes(videoId) ? current.filter((id) => id !== videoId) : [...current, videoId]
    ));
  }

  async function removeBgmForSelectedVideos() {
    if (selectedBgmVideoIds.length === 0) {
      props.setError("请先选择需要消除 BGM 的成片。");
      return;
    }
    await Promise.all(selectedBgmVideoIds.map((videoId) => requestRemoveBgm(videoId, false)));
    props.setMessage(`已为 ${selectedBgmVideoIds.length} 个成片创建消除 BGM 任务。`);
    setSelectedBgmVideoIds([]);
    setShowBgmDialog(false);
  }

  return (
    <>
      <section className="import-mode-grid">
        <div className="panel import-mode-panel finished-import-panel">
          <div className="section-title compact-title">
            <div>
              <h2>成片导入拆分</h2>
              <p>导入带口播成片，自动 ASR、语义切分、打大类 tag。</p>
            </div>
            <div className="import-primary-actions">
              <button className="secondary" disabled={finishedVideos.length === 0} onClick={() => setShowBgmDialog(true)}>消除 BGM</button>
              <button className="secondary" disabled={finishedBatchBusy || finishedVideos.length === 0} onClick={reanalyzeFinishedBatch}>
                {finishedBatchBusy ? "分析中..." : "重新批量分析"}
              </button>
              <button className="primary-action" disabled={importing} onClick={openFinishedFilePicker}>
                {importing ? "导入中..." : "导入并自动分析"}
              </button>
            </div>
          </div>
          <input
            ref={finishedFileInputRef}
            className="file-input-hidden"
            type="file"
            accept="video/*"
            multiple
            onChange={handleFinishedFilesSelected}
          />
          <section className="inline-result-section">
            <div className="video-grid compact-video-grid">
              {finishedVideos.map((video) => {
                const videoSegments = props.segments.filter((segment) => segment.video_id === video.id);
                const timestamped = hasTranscriptSegments(video);
                return (
                  <article className="video-card" key={video.id}>
                    <div className="video-preview-stack">
                      <video
                        src={`${API_BASE_URL}/videos/${video.id}/preview`}
                        poster={`${API_BASE_URL}/videos/${video.id}/thumbnail`}
                        controls
                        preload="metadata"
                      />
                      <VideoSegmentSummary segments={videoSegments} transcript={video.transcript} />
                    </div>
                    <div>
                      <div className="video-card-header">
                        <div>
                          <h2>{video.name}</h2>
                          <p>{video.width}x{video.height} · {video.duration_seconds.toFixed(1)}s · {statusLabel(video.status)}</p>
                        </div>
                        <button className="ghost-button" disabled={reanalyzingId === video.id} onClick={() => reanalyzeVideo(video.id)}>
                          {reanalyzingId === video.id ? "分析中..." : "重新分析"}
                        </button>
                      </div>
                      {video.status === "segmented" && !timestamped && (
                        <p className="field-hint warning-hint">当前视频没有 ASR 时间戳，片段边界为估算结果；重新分析后会更准。</p>
                      )}
                      {video.error_message && <p className="error">{video.error_message}</p>}
                      {["transcribing", "segmenting", "imported", "transcribed"].includes(video.status) && <div className="progress-strip"><span /></div>}
                      <VideoScriptList segments={videoSegments} />
                    </div>
                  </article>
                );
              })}
              {finishedVideos.length === 0 && <p className="empty panel">还没有成片分析结果。</p>}
            </div>
          </section>
        </div>

        <div className="panel import-mode-panel loose-import-panel">
          <div className="section-title compact-title">
            <div>
              <h2>导入零散素材并自动分析</h2>
              <p>先输入产品卖点 tag，再导入产品展示、权益镜头或真人口播，AI 会按这些 tag 辅助识别。</p>
            </div>
            <div className="import-primary-actions">
              <div className="inline-tag-vocab">
                <TagInputChips
                  value={customTagDraft}
                  onChange={setCustomTagDraft}
                  placeholder="卖点/画面 tag"
                />
                <button className="secondary" onClick={() => saveCustomTags()}>保存</button>
              </div>
              <button className="secondary" disabled={batchTaggingBusy || productSegments.length === 0} onClick={analyzeProductBatch}>
                {batchTaggingBusy ? "分析中..." : "重新批量分析"}
              </button>
              <button className="primary-action" disabled={assetImporting} onClick={openLooseFilePicker}>
                {assetImporting ? "分析中..." : "导入并自动分析"}
              </button>
            </div>
          </div>
          <input
            ref={looseFileInputRef}
            className="file-input-hidden"
            type="file"
            accept="video/*"
            multiple
            onChange={handleLooseFilesSelected}
          />
          <div className="product-tagging-card inline-result-section">
            <div className="video-grid compact-video-grid">
              {productSegments.slice(0, 8).map((segment) => (
                <article className="video-card product-preview-card" key={segment.id}>
                  <div className="video-preview-stack">
                    <video
                      src={`${API_BASE_URL}/segments/${segment.id}/preview`}
                      poster={`${API_BASE_URL}/segments/${segment.id}/thumbnail`}
                      controls
                      preload="metadata"
                    />
                  </div>
                  <div>
                    <div className="video-card-header">
                      <div>
                        <h2>{segment.video_name}</h2>
                        <p>{formatClockPrecise(segment.start_seconds)} - {formatClockPrecise(segment.end_seconds)}</p>
                      </div>
                      <button className="secondary" disabled={taggingSegmentId === segment.id} onClick={() => analyzeVisual(segment.id)}>
                        {taggingSegmentId === segment.id ? "打标中..." : "AI 打标"}
                      </button>
                    </div>
                    <p>{segment.visual_description || "待分析"}</p>
                    <div className="tag-line"><CompactTagChips values={[...splitMultiValue(segment.selling_points), ...splitMultiValue(segment.visual_tags)]} limit={3} /></div>
                  </div>
                </article>
              ))}
              {productSegments.length === 0 && <p className="empty">导入产品展示/权益镜头后会出现在这里。</p>}
            </div>
          </div>
        </div>
      </section>
      {showBgmDialog && (
        <div className="modal-backdrop" onClick={() => setShowBgmDialog(false)}>
          <section className="bgm-select-dialog" onClick={(event) => event.stopPropagation()}>
            <div className="split-head">
              <div>
                <h2>消除 BGM</h2>
                <p>勾选需要创建人声/BGM 分离任务的成片。</p>
              </div>
              <button className="secondary" onClick={() => setShowBgmDialog(false)}>关闭</button>
            </div>
            <label className="checkbox-line compact-check bgm-select-all">
              <input
                checked={finishedVideos.length > 0 && selectedBgmVideoIds.length === finishedVideos.length}
                onChange={(event) => setSelectedBgmVideoIds(event.target.checked ? finishedVideos.map((video) => video.id) : [])}
                type="checkbox"
              />
              全选
            </label>
            <div className="bgm-select-list">
              {finishedVideos.map((video) => (
                <label className="checkbox-line compact-check" key={video.id}>
                  <input checked={selectedBgmVideoIds.includes(video.id)} onChange={() => toggleBgmVideo(video.id)} type="checkbox" />
                  <span>{video.name}</span>
                </label>
              ))}
            </div>
            <div className="modal-actions">
              <button className="secondary" onClick={() => setShowBgmDialog(false)}>取消</button>
              <button className="primary-action" disabled={selectedBgmVideoIds.length === 0} onClick={removeBgmForSelectedVideos}>创建任务 {selectedBgmVideoIds.length}</button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}

function hasTranscriptSegments(video: VideoItem) {
  try {
    const segments = JSON.parse(video.transcript_segments || "[]");
    return Array.isArray(segments) && segments.length > 0;
  } catch {
    return false;
  }
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    imported: "已导入，等待处理",
    transcribing: "正在转录",
    transcribed: "已转录，等待切分",
    segmenting: "正在语义切分",
    segmented: "已完成",
    failed: "处理失败",
  };
  return labels[status] ?? status;
}

function VideoSegmentSummary(props: { segments: Segment[]; transcript: string }) {
  const tagCounts = props.segments.reduce<Record<string, number>>((counts, segment) => {
    counts[segment.semantic_type] = (counts[segment.semantic_type] ?? 0) + 1;
    return counts;
  }, {});
  const orderedTags = Object.entries(tagCounts).sort((a, b) => b[1] - a[1]);
  const wordCount = props.transcript.length;

  return (
    <div className="video-analysis-summary">
      <div className="analysis-meta">
        <span>台词 {wordCount}字</span>
        <span>{props.segments.length} 个片段</span>
      </div>
      {orderedTags.length > 0 ? (
        <div className="tag-counts">
          {orderedTags.slice(0, 3).map(([tag, count]) => (
            <span className={`tag-chip tag-count-chip ${tagColorClass(tag)}`} key={tag}>{tag} {count}</span>
          ))}
          {orderedTags.length > 3 && (
            <span
              className="tag-chip tag-color-default tag-overflow-chip"
              data-overflow={orderedTags.slice(3).map(([tag, count]) => `${tag} ${count}`).join(" / ")}
              title={orderedTags.slice(3).map(([tag, count]) => `${tag} ${count}`).join(" / ")}
            >
              ...
            </span>
          )}
        </div>
      ) : (
        <p className="empty">自动分析完成后会显示 tag 统计。</p>
      )}
    </div>
  );
}

function VideoScriptList(props: { segments: Segment[] }) {
  if (props.segments.length === 0) {
    return <p className="empty script-empty">片段会在自动切分完成后显示在这里。</p>;
  }

  const orderedSegments = [...props.segments].sort((a, b) => a.start_seconds - b.start_seconds);

  return (
    <div className="script-list">
      <div className="script-list-title">
        <strong>台词</strong>
        <span>{orderedSegments.length} 句</span>
      </div>
      {orderedSegments.map((segment) => (
        <div className="script-line" key={segment.id}>
          <span className="script-time">
            {formatClock(segment.start_seconds)}
          </span>
          <span className="script-tag-list">{splitMultiValue(segment.semantic_type).map((tag) => <TagChip key={tag} tag={tag} />)}</span>
          <p>{segment.text}</p>
        </div>
      ))}
    </div>
  );
}

function AssetWorkspace(props: { project: Project; segments: Segment[]; videos: VideoItem[]; onRefresh: () => void; setError: (value: string) => void; setMessage: (value: string) => void }) {
  return (
    <section className="asset-segment-library">
      <SegmentLibrary segments={props.segments} videos={props.videos} onRefresh={props.onRefresh} setError={props.setError} setMessage={props.setMessage} />
    </section>
  );
}

function ScriptWorkspace(props: { project: Project; setError: (value: string) => void; setMessage: (value: string) => void }) {
  const [scripts, setScripts] = useState<ScriptDraft[]>([]);
  const [voiceAssets, setVoiceAssets] = useState<Asset[]>([]);
  const [bgmAssets, setBgmAssets] = useState<Asset[]>([]);
  const [selectedVoiceByScript, setSelectedVoiceByScript] = useState<Record<number, string>>({});
  const [selectedBgmId, setSelectedBgmId] = useState("");
  const [voiceBusyScriptId, setVoiceBusyScriptId] = useState<number | null>(null);
  const [editingScriptId, setEditingScriptId] = useState<number | null>(null);
  const [scriptDrafts, setScriptDrafts] = useState<Record<number, ScriptDraft>>({});
  const [sourceText, setSourceText] = useState("");
  const [productContext, setProductContext] = useState("");
  const [douyinUrl, setDouyinUrl] = useState("");
  const [scriptQuery, setScriptQuery] = useState("");
  const [scriptSourceFilter, setScriptSourceFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const filteredScripts = scripts.filter((script) => {
    const sourceMatches = !scriptSourceFilter || script.source_type === scriptSourceFilter;
    const haystack = `${script.title} ${script.source_type} ${script.lines.map((line) => `${line.text} ${line.semantic_type} ${line.selling_points.join(" ")} ${line.visual_needs.join(" ")}`).join(" ")}`.toLowerCase();
    return sourceMatches && (!scriptQuery.trim() || haystack.includes(scriptQuery.trim().toLowerCase()));
  });
  const scriptSourceCounts = scripts.reduce<Record<string, number>>((counts, script) => {
    counts[script.source_type] = (counts[script.source_type] ?? 0) + 1;
    return counts;
  }, {});
  const scriptKeywordSummary = Array.from(scripts.reduce<Map<string, number>>((groups, script) => {
    script.lines.forEach((line) => {
      [...line.selling_points, ...line.visual_needs].forEach((tag) => {
        const trimmed = tag.trim();
        if (trimmed) groups.set(trimmed, (groups.get(trimmed) ?? 0) + 1);
      });
    });
    return groups;
  }, new Map()).entries()).sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0])).slice(0, 10);
  useEffect(() => {
    void loadScripts();
    void loadScriptAssets();
  }, [props.project.id]);

  async function loadScripts() {
    try {
      setScripts(await api<ScriptDraft[]>(`/projects/${props.project.id}/scripts`));
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "文案加载失败");
    }
  }

  async function loadScriptAssets() {
    try {
      const [voices, bgms] = await Promise.all([
        api<Asset[]>(`/projects/${props.project.id}/assets?asset_type=voice`),
        api<Asset[]>(`/projects/${props.project.id}/assets?asset_type=bgm`),
      ]);
      setVoiceAssets(voices);
      setBgmAssets(bgms);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "声音素材加载失败");
    }
  }

  async function generate(kind: "manual" | "douyin") {
    setBusy(true);
    try {
      const script = await api<ScriptDraft>(kind === "manual" ? "/scripts/generate-variants" : "/scripts/from-douyin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(kind === "manual"
          ? { project_id: props.project.id, source_text: sourceText, product_context: productContext, title: "AI 裂变文案" }
          : { project_id: props.project.id, douyin_url: douyinUrl, extracted_text: sourceText, product_context: productContext }),
      });
      props.setMessage(`已生成文案：${script.title}`);
      await loadScripts();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "文案生成失败");
    } finally {
      setBusy(false);
    }
  }

  async function generateVoiceForScript(script: ScriptDraft) {
    const text = script.lines.map((line) => line.text).join("\n");
    if (!text.trim()) {
      props.setError("这个文案没有可用于配音的句子。");
      return;
    }
    setVoiceBusyScriptId(script.id);
    try {
      const asset = await api<Asset>("/tts/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: props.project.id, text, title: `${script.title} 配音`, script_id: script.id }),
      });
      setVoiceAssets((current) => [asset, ...current.filter((item) => item.id !== asset.id)]);
      setSelectedVoiceByScript((current) => ({ ...current, [script.id]: String(asset.id) }));
      props.setMessage(`已生成文案配音：${asset.name}`);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "文案配音生成失败");
    } finally {
      setVoiceBusyScriptId(null);
    }
  }

  async function generateTimeline(script: ScriptDraft) {
    try {
      const timeline = await api<MaterialMixTimeline>("/timelines/generate-from-voice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: props.project.id,
          script_id: script.id,
          voice_asset_id: selectedVoiceByScript[script.id] ? Number(selectedVoiceByScript[script.id]) : undefined,
          bgm_asset_id: selectedBgmId ? Number(selectedBgmId) : undefined,
          name: `${script.title} 成片`,
        }),
      });
      props.setMessage(`已按文案语义生成时间线：${timeline.name}`);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "生成时间线失败");
    }
  }

  function startEditScript(script: ScriptDraft) {
    setEditingScriptId(script.id);
    setScriptDrafts((current) => ({ ...current, [script.id]: structuredClone(script) }));
  }

  function updateScriptDraft(scriptId: number, updater: (script: ScriptDraft) => ScriptDraft) {
    setScriptDrafts((current) => {
      const source = current[scriptId] ?? scripts.find((script) => script.id === scriptId);
      if (!source) return current;
      return { ...current, [scriptId]: updater(structuredClone(source)) };
    });
  }

  async function saveScriptDraft(scriptId: number) {
    const draft = scriptDrafts[scriptId];
    if (!draft) return;
    try {
      const updated = await api<ScriptDraft>(`/scripts/${scriptId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: draft.title,
          source_text: draft.source_text,
          product_context: draft.product_context,
          lines: draft.lines,
        }),
      });
      setScripts((current) => current.map((script) => (script.id === updated.id ? updated : script)));
      setEditingScriptId(null);
      props.setMessage("文案已保存，后续配音和时间线会使用修改后的版本。");
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "保存文案失败");
    }
  }

  function updateScriptLine(scriptId: number, lineIndex: number, values: Partial<ScriptLine>) {
    updateScriptDraft(scriptId, (script) => ({
      ...script,
      lines: script.lines.map((line, index) => (
        index === lineIndex ? { ...line, ...values } : line
      )),
    }));
  }

  function addScriptLine(scriptId: number) {
    updateScriptDraft(scriptId, (script) => ({
      ...script,
      lines: [
        ...script.lines,
        {
          line_index: script.lines.length + 1,
          text: "",
          semantic_type: "过渡",
          selling_points: [],
          visual_needs: [],
          estimated_duration: 2,
        },
      ],
    }));
  }

  function removeScriptLine(scriptId: number, lineIndex: number) {
    updateScriptDraft(scriptId, (script) => ({
      ...script,
      lines: script.lines
        .filter((_, index) => index !== lineIndex)
        .map((line, index) => ({ ...line, line_index: index + 1 })),
    }));
  }

  return (
    <section className="scheme-layout">
      <section className="panel generation-panel">
        <h2>文案中心</h2>
        <label>产品信息</label>
        <textarea rows={5} value={productContext} onChange={(event) => setProductContext(event.target.value)} placeholder="产品卖点、人群、价格权益、禁用词..." />
        <label>手动文案 / 抖音拆解文本</label>
        <textarea rows={8} value={sourceText} onChange={(event) => setSourceText(event.target.value)} placeholder="粘贴基础文案；如果是抖音链接，也可以先粘贴识别出的原文案。" />
        <label>抖音链接</label>
        <input value={douyinUrl} onChange={(event) => setDouyinUrl(event.target.value)} placeholder="用于记录来源和结构改写" />
        <div className="action-row">
          <button className="primary-action" disabled={busy || !sourceText.trim()} onClick={() => generate("manual")}>手动文案裂变</button>
          <button className="secondary" disabled={busy || !douyinUrl.trim()} onClick={() => generate("douyin")}>抖音结构改写</button>
        </div>
        <label>BGM 偏好</label>
        <select value={selectedBgmId} onChange={(event) => setSelectedBgmId(event.target.value)}>
          <option value="">不指定 BGM</option>
          {bgmAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
        </select>
      </section>
      <aside className="panel">
        <h2>文案版本</h2>
        <div className="script-filter-panel">
          <input value={scriptQuery} onChange={(event) => setScriptQuery(event.target.value)} placeholder="搜索文案、语义、卖点或画面需求" />
          <select value={scriptSourceFilter} onChange={(event) => setScriptSourceFilter(event.target.value)}>
            <option value="">全部来源 {scripts.length}</option>
            {Object.entries(scriptSourceCounts).map(([source, count]) => <option key={source} value={source}>{source} {count}</option>)}
          </select>
        </div>
        {scriptKeywordSummary.length > 0 && (
          <div className="tag-line script-summary-tags">
            {scriptKeywordSummary.map(([tag, count]) => <span className="tag-chip tag-color-default" key={tag}>{tag} {count}</span>)}
          </div>
        )}
        <p className="field-hint">当前显示 {filteredScripts.length} / {scripts.length} 个文案版本。</p>
        {filteredScripts.map((script) => {
          const estimatedDuration = script.lines.reduce((sum, line) => sum + Number(line.estimated_duration || 0), 0);
          const sellingPointTags = Array.from(new Set(script.lines.flatMap((line) => line.selling_points))).slice(0, 6);
          const visualNeedTags = Array.from(new Set(script.lines.flatMap((line) => line.visual_needs))).slice(0, 6);
          return (
          <article className="scheme-card" key={script.id}>
            {editingScriptId === script.id ? (
              <ScriptEditor
                script={scriptDrafts[script.id] ?? script}
                onCancel={() => setEditingScriptId(null)}
                onSave={() => saveScriptDraft(script.id)}
                onTitleChange={(value) => updateScriptDraft(script.id, (draft) => ({ ...draft, title: value }))}
                onLineChange={(lineIndex, values) => updateScriptLine(script.id, lineIndex, values)}
                onAddLine={() => addScriptLine(script.id)}
                onRemoveLine={(lineIndex) => removeScriptLine(script.id, lineIndex)}
              />
            ) : (
              <>
                <strong>{script.title}</strong>
                <span>{script.lines.length} 句 · 约 {estimatedDuration.toFixed(1)}s · {script.source_type}</span>
                {(sellingPointTags.length > 0 || visualNeedTags.length > 0) && (
                  <div className="tag-line">
                    {sellingPointTags.map((tag) => <span className="tag-chip tag-color-default" key={`sp-${script.id}-${tag}`}>卖点 · {tag}</span>)}
                    {visualNeedTags.map((tag) => <span className="tag-chip tag-color-default" key={`vn-${script.id}-${tag}`}>画面 · {tag}</span>)}
                  </div>
                )}
                {script.lines.slice(0, 4).map((line) => <p key={line.line_index}>{line.line_index}. {line.text}</p>)}
                <button className="ghost-button" onClick={() => startEditScript(script)}>编辑文案</button>
              </>
            )}
            <select value={selectedVoiceByScript[script.id] ?? ""} onChange={(event) => setSelectedVoiceByScript((current) => ({ ...current, [script.id]: event.target.value }))}>
              <option value="">不指定配音</option>
              {voiceAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
            </select>
            {selectedVoiceByScript[script.id] && <audio src={`${API_BASE_URL}/assets/${selectedVoiceByScript[script.id]}/file`} controls />}
            <div className="action-row">
              <button className="secondary" disabled={voiceBusyScriptId === script.id} onClick={() => generateVoiceForScript(script)}>
                {voiceBusyScriptId === script.id ? "配音中..." : "生成配音"}
              </button>
              <button className="secondary" onClick={() => generateTimeline(script)}>按语义填充素材</button>
            </div>
          </article>
        )})}
        {scripts.length === 0 && <p className="empty">生成后的文案会显示在这里。</p>}
        {scripts.length > 0 && filteredScripts.length === 0 && <p className="empty">没有匹配当前筛选的文案。</p>}
      </aside>
    </section>
  );
}

function ScriptEditor(props: {
  script: ScriptDraft;
  onTitleChange: (value: string) => void;
  onLineChange: (lineIndex: number, values: Partial<ScriptLine>) => void;
  onAddLine: () => void;
  onRemoveLine: (lineIndex: number) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="script-editor-inline">
      <label>标题
        <input value={props.script.title} onChange={(event) => props.onTitleChange(event.target.value)} />
      </label>
      {props.script.lines.map((line, index) => (
        <section className="script-line-editor" key={`${line.line_index}-${index}`}>
          <div className="timeline-clip-meta">
            <strong>#{index + 1}</strong>
            <select value={line.semantic_type} onChange={(event) => props.onLineChange(index, { semantic_type: event.target.value })}>
              {SEGMENT_TYPES.map((tag) => <option key={tag} value={tag}>{tag}</option>)}
            </select>
            <input
              max={30}
              min={0.8}
              step={0.1}
              type="number"
              value={line.estimated_duration}
              onChange={(event) => props.onLineChange(index, { estimated_duration: Number(event.target.value) })}
            />
          </div>
          <textarea rows={3} value={line.text} onChange={(event) => props.onLineChange(index, { text: event.target.value })} />
          <div className="edit-grid compact">
            <label>卖点
              <input value={line.selling_points.join(",")} onChange={(event) => props.onLineChange(index, { selling_points: splitMultiValue(event.target.value) })} />
            </label>
            <label>画面需求
              <input value={line.visual_needs.join(",")} onChange={(event) => props.onLineChange(index, { visual_needs: splitMultiValue(event.target.value) })} />
            </label>
          </div>
          <button className="danger-action" onClick={() => props.onRemoveLine(index)}>删除这一句</button>
        </section>
      ))}
      <div className="action-row">
        <button className="secondary" onClick={props.onAddLine}>添加一句</button>
        <button className="ghost-button" onClick={props.onCancel}>取消</button>
        <button className="primary-action" onClick={props.onSave}>保存文案</button>
      </div>
    </div>
  );
}

function VoiceWorkspace(props: { project: Project; setError: (value: string) => void; setMessage: (value: string) => void }) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [text, setText] = useState("");
  const [voice, setVoice] = useState("alloy");
  const [busy, setBusy] = useState(false);
  const [analyzingAssetId, setAnalyzingAssetId] = useState<number | null>(null);
  useEffect(() => { void loadAssets(); }, [props.project.id]);

  async function loadAssets() {
    try {
      const [voices, bgms] = await Promise.all([
        api<Asset[]>(`/projects/${props.project.id}/assets?asset_type=voice`),
        api<Asset[]>(`/projects/${props.project.id}/assets?asset_type=bgm`),
      ]);
      setAssets([...voices, ...bgms]);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "声音素材加载失败");
    }
  }

  async function generateVoice() {
    setBusy(true);
    try {
      const asset = await api<Asset>("/tts/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: props.project.id, text, voice, title: "AI 口播配音" }),
      });
      props.setMessage(`已生成配音素材：${asset.name}`);
      await loadAssets();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "配音生成失败");
    } finally {
      setBusy(false);
    }
  }

  async function analyzeAudioAsset(asset: Asset) {
    setAnalyzingAssetId(asset.id);
    try {
      const updated = await api<Asset>(`/assets/${asset.id}/analyze-audio`, { method: "POST" });
      setAssets((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      const analysis = updated.metadata?.audio_analysis as Record<string, unknown> | undefined;
      props.setMessage(`已分析响度：${updated.name}${analysis?.input_i ? `，${analysis.input_i} LUFS` : ""}`);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "响度分析失败");
    } finally {
      setAnalyzingAssetId(null);
    }
  }

  return (
    <section className="overview-grid">
      <div className="panel settings-panel">
        <h2>TTS 配音</h2>
        <label>音色</label>
        <input value={voice} onChange={(event) => setVoice(event.target.value)} placeholder="预制音色或供应商音色 ID" />
        <label>口播文本</label>
        <textarea rows={10} value={text} onChange={(event) => setText(event.target.value)} />
        <button className="primary-action" disabled={busy || !text.trim()} onClick={generateVoice}>{busy ? "生成中..." : "生成配音"}</button>
        <p className="field-hint">未配置 TTS 服务时会生成静音占位音频，用于先跑通“配音驱动时间线”。</p>
      </div>
      <div className="panel overview-panel">
        <h2>声音素材</h2>
        {assets.map((asset) => {
          const analysis = asset.metadata?.audio_analysis as Record<string, unknown> | undefined;
          const loudness = typeof analysis?.input_i === "string" || typeof analysis?.input_i === "number" ? `${analysis.input_i} LUFS` : "";
          return (
            <div className="compact-row" key={asset.id}>
              <span>{asset.name}</span>
              {(asset.asset_type === "voice" || asset.asset_type === "bgm") ? <audio src={`${API_BASE_URL}/assets/${asset.id}/file`} controls /> : <strong>{asset.asset_type}</strong>}
              {loudness && <strong>{loudness}</strong>}
              <button className="ghost-button" disabled={analyzingAssetId === asset.id} onClick={() => analyzeAudioAsset(asset)}>
                {analyzingAssetId === asset.id ? "分析中..." : "分析响度"}
              </button>
            </div>
          );
        })}
        {assets.length === 0 && <p className="empty">在素材库导入 BGM，或在这里生成配音。</p>}
      </div>
    </section>
  );
}

function SubtitleWorkspace(props: { project: Project; setError: (value: string) => void; setMessage: (value: string) => void }) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selectedAssetId, setSelectedAssetId] = useState<number | null>(null);
  const [styleDraft, setStyleDraft] = useState<SubtitleStyleDraft>(subtitleStyleFromAsset());
  const [saving, setSaving] = useState(false);
  useEffect(() => { void loadAssets(); }, [props.project.id]);
  const selectedAsset = assets.find((asset) => asset.id === selectedAssetId) ?? assets[0];

  useEffect(() => {
    if (!selectedAsset) return;
    setSelectedAssetId(selectedAsset.id);
    setStyleDraft(subtitleStyleFromAsset(selectedAsset));
  }, [selectedAsset?.id]);

  async function loadAssets() {
    try {
      const nextAssets = await api<Asset[]>(`/projects/${props.project.id}/assets?asset_type=subtitle_preset`);
      setAssets(nextAssets);
      if (!selectedAssetId && nextAssets[0]) {
        setSelectedAssetId(nextAssets[0].id);
      }
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "字幕预设加载失败");
    }
  }

  async function saveSubtitleStyle() {
    if (!selectedAsset) return;
    setSaving(true);
    try {
      const updated = await api<Asset>(`/assets/${selectedAsset.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ metadata: { ...(selectedAsset.metadata || {}), subtitle_style: styleDraft } }),
      });
      setAssets((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      props.setMessage(`已保存字幕样式：${updated.name}`);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "字幕样式保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="overview-grid">
      <div className="panel overview-panel">
        <h2>字幕模板</h2>
        <p className="field-hint">V1 使用 ASS 字幕烧录；导入的 .ass/.json 可直接作为模板，也可以在这里覆盖常用样式参数。</p>
        {assets.map((asset) => (
          <button className={`timeline-row-button ${selectedAsset?.id === asset.id ? "active" : ""}`} key={asset.id} onClick={() => setSelectedAssetId(asset.id)}>
            <span>{asset.name}</span>
            <strong>{asset.status}</strong>
          </button>
        ))}
        {assets.length === 0 && <p className="empty">可以在素材库选择“字幕预设”导入 .ass/.json/.txt。</p>}
      </div>
      <div className="panel settings-panel">
        <h2>样式编辑</h2>
        {selectedAsset ? (
          <>
            <label>字体
              <input value={styleDraft.font} onChange={(event) => setStyleDraft({ ...styleDraft, font: event.target.value })} />
            </label>
            <label>字号
              <input min={20} max={120} type="number" value={styleDraft.size} onChange={(event) => setStyleDraft({ ...styleDraft, size: Number(event.target.value) })} />
            </label>
            <label>主色 ASS
              <input value={styleDraft.primary_color} onChange={(event) => setStyleDraft({ ...styleDraft, primary_color: event.target.value })} />
            </label>
            <label>描边色 ASS
              <input value={styleDraft.outline_color} onChange={(event) => setStyleDraft({ ...styleDraft, outline_color: event.target.value })} />
            </label>
            <label>背景色 ASS
              <input value={styleDraft.back_color} onChange={(event) => setStyleDraft({ ...styleDraft, back_color: event.target.value })} />
            </label>
            <label className="checkbox-line">
              <input checked={styleDraft.bold} type="checkbox" onChange={(event) => setStyleDraft({ ...styleDraft, bold: event.target.checked })} />
              加粗
            </label>
            <label>描边
              <input min={0} max={12} step={0.5} type="number" value={styleDraft.outline} onChange={(event) => setStyleDraft({ ...styleDraft, outline: Number(event.target.value) })} />
            </label>
            <label>阴影
              <input min={0} max={8} step={0.5} type="number" value={styleDraft.shadow} onChange={(event) => setStyleDraft({ ...styleDraft, shadow: Number(event.target.value) })} />
            </label>
            <label>位置
              <select value={styleDraft.alignment} onChange={(event) => setStyleDraft({ ...styleDraft, alignment: Number(event.target.value) })}>
                <option value={2}>底部居中</option>
                <option value={5}>画面居中</option>
                <option value={8}>顶部居中</option>
              </select>
            </label>
            <label>底部边距
              <input min={20} max={500} step={10} type="number" value={styleDraft.margin_v} onChange={(event) => setStyleDraft({ ...styleDraft, margin_v: Number(event.target.value) })} />
            </label>
            <button className="primary-action" disabled={saving} onClick={saveSubtitleStyle}>{saving ? "保存中..." : "保存字幕样式"}</button>
          </>
        ) : (
          <p className="empty">导入字幕预设后，可在这里调整字体、描边、阴影和位置。</p>
        )}
      </div>
    </section>
  );
}

function formatClock(seconds: number) {
  const safe = Math.max(0, Math.floor(seconds));
  const minute = Math.floor(safe / 60);
  const second = safe % 60;
  return `${minute}:${String(second).padStart(2, "0")}`;
}

function formatClockPrecise(seconds: number) {
  const safe = Math.max(0, seconds);
  const minute = Math.floor(safe / 60);
  const second = safe - minute * 60;
  return `${minute}:${second.toFixed(1).padStart(4, "0")}`;
}

function handleVideoShortcut(event: KeyboardEvent<HTMLVideoElement>) {
  const video = event.currentTarget;
  if (event.key === " ") {
    event.preventDefault();
    if (video.paused) {
      void video.play().catch(() => undefined);
    } else {
      video.pause();
    }
    return;
  }
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    const step = event.shiftKey ? 2 : 0.5;
    const direction = event.key === "ArrowRight" ? 1 : -1;
    video.currentTime = Math.max(0, Math.min(video.duration || Number.MAX_SAFE_INTEGER, video.currentTime + direction * step));
  }
}

function useVideoKeyboardShortcuts(videoRef: RefObject<HTMLVideoElement | null>, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      const video = videoRef.current;
      if (!video) return;
      if (event.key === " ") {
        event.preventDefault();
        if (video.paused) {
          void video.play().catch(() => undefined);
        } else {
          video.pause();
        }
        return;
      }
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const step = event.shiftKey ? 2 : 0.5;
        const direction = event.key === "ArrowRight" ? 1 : -1;
        video.currentTime = Math.max(0, Math.min(video.duration || Number.MAX_SAFE_INTEGER, video.currentTime + direction * step));
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [enabled, videoRef]);
}

function useCloseTagMenusOnOutsideClick() {
  useEffect(() => {
    function closeMenus(event: PointerEvent) {
      const target = event.target as Node | null;
      document.querySelectorAll<HTMLDetailsElement>("details.card-tag-picker[open], details.inline-multi-select[open]").forEach((details) => {
        if (target && details.contains(target)) return;
        details.open = false;
      });
    }
    document.addEventListener("pointerdown", closeMenus, true);
    return () => document.removeEventListener("pointerdown", closeMenus, true);
  }, []);
}

function splitMultiValue(value: string | undefined) {
  return (value ?? "").split(/[,，、\n]/).map((item) => item.trim()).filter(Boolean);
}

function joinMultiValue(values: string[]) {
  return values.join(",");
}

function multiValueIncludes(value: string, expected: string) {
  return splitMultiValue(value).includes(expected);
}

function multiValuesOverlap(value: string, expected: string) {
  const expectedValues = splitMultiValue(expected);
  if (expectedValues.length === 0) return false;
  return expectedValues.some((item) => multiValueIncludes(value, item));
}

function assetInputLoudness(asset?: Asset) {
  const analysis = asset?.metadata?.audio_analysis as Record<string, unknown> | undefined;
  const value = analysis?.input_i;
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function subtitleStyleFromAsset(asset?: Asset): SubtitleStyleDraft {
  const style = asset?.metadata?.subtitle_style as Partial<SubtitleStyleDraft> | undefined;
  return {
    font: String(style?.font || "Arial"),
    size: Number(style?.size || 64),
    primary_color: String(style?.primary_color || "&H00FFFFFF"),
    outline_color: String(style?.outline_color || "&H00111111"),
    back_color: String(style?.back_color || "&H66000000"),
    bold: style?.bold !== false,
    outline: Number(style?.outline ?? 4),
    shadow: Number(style?.shadow ?? 1),
    alignment: Number(style?.alignment || 2),
    margin_v: Number(style?.margin_v || 150),
  };
}

function tagColorClass(tag: string) {
  const index = SEGMENT_TYPES.indexOf(tag);
  return index >= 0 ? `tag-color-${index}` : "tag-color-default";
}

function TagChip(props: { tag: string; className?: string }) {
  return <span className={`tag-chip ${tagColorClass(props.tag)} ${props.className ?? ""}`.trim()}>{props.tag}</span>;
}

function TagInputChips(props: { value: string; onChange: (value: string) => void; placeholder?: string }) {
  const [draft, setDraft] = useState("");
  const tags = splitMultiValue(props.value);

  function commit(input = draft) {
    const nextTags = splitMultiValue(input);
    if (nextTags.length === 0) return;
    props.onChange(joinMultiValue(Array.from(new Set([...tags, ...nextTags]))));
    setDraft("");
  }

  function removeTag(tag: string) {
    props.onChange(joinMultiValue(tags.filter((item) => item !== tag)));
  }

  return (
    <div className="tag-input-box">
      <div className="tag-input-row">
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit();
            }
          }}
          onPaste={(event) => {
            const text = event.clipboardData.getData("text");
            if (/[,，、\n]/.test(text)) {
              event.preventDefault();
              commit(text);
            }
          }}
          placeholder={props.placeholder ?? "输入 tag 后回车"}
        />
        <button className="secondary" disabled={!draft.trim()} onClick={() => commit()}>录入</button>
      </div>
      <div className="tag-input-chips">
        {tags.map((tag) => (
          <button className="tag-chip tag-color-default tag-remove-chip" key={tag} onClick={() => removeTag(tag)} title="点击删除">
            {tag} ×
          </button>
        ))}
        {tags.length === 0 && <span className="tag-input-empty">还没有录入 tag</span>}
      </div>
    </div>
  );
}

function parseTranscriptSegments(value: string | undefined): TranscriptSegment[] {
  try {
    const parsed = JSON.parse(value || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item) => ({
        start_seconds: Number(item?.start_seconds),
        end_seconds: Number(item?.end_seconds),
        text: String(item?.text ?? "").trim(),
      }))
      .filter((item) => Number.isFinite(item.start_seconds) && Number.isFinite(item.end_seconds) && item.end_seconds > item.start_seconds && item.text);
  } catch {
    return [];
  }
}

function MaterialMixWorkspace(props: {
  project: Project;
  segments: Segment[];
  setMessage: (value: string) => void;
  setError: (value: string) => void;
}) {
  const [timelines, setTimelines] = useState<MaterialMixTimeline[]>([]);
  const [selectedTimelineId, setSelectedTimelineId] = useState<number | null>(null);
  const [selectedTimeline, setSelectedTimeline] = useState<MaterialMixTimeline | null>(null);
  const [newTimelineName, setNewTimelineName] = useState("素材混剪方案 01");
  const [generationPrompt, setGenerationPrompt] = useState("");
  const [targetClipCount, setTargetClipCount] = useState(8);
  const [preferDistinctSources, setPreferDistinctSources] = useState(true);
  const [generationWarnings, setGenerationWarnings] = useState<string[]>([]);
  const [generationNotes, setGenerationNotes] = useState<Record<number, string>>({});
  const [replacementClipId, setReplacementClipId] = useState<number | null>(null);
  const [renamingTimelineId, setRenamingTimelineId] = useState<number | null>(null);
  const [renameTimelineValue, setRenameTimelineValue] = useState("");
  const [showSegmentPicker, setShowSegmentPicker] = useState(false);
  const [query, setQuery] = useState("");
  const [outputDir, setOutputDir] = useState("");
  const [voiceAssets, setVoiceAssets] = useState<Asset[]>([]);
  const [bgmAssets, setBgmAssets] = useState<Asset[]>([]);
  const [subtitleAssets, setSubtitleAssets] = useState<Asset[]>([]);
  const [audioPolicy, setAudioPolicy] = useState("keep_original");
  const [voiceAssetId, setVoiceAssetId] = useState("");
  const [bgmAssetId, setBgmAssetId] = useState("");
  const [normalizeLoudness, setNormalizeLoudness] = useState(true);
  const [targetLufs, setTargetLufs] = useState(-14);
  const [burnSubtitles, setBurnSubtitles] = useState(false);
  const [subtitlePresetId, setSubtitlePresetId] = useState("");
  const [previewVersion, setPreviewVersion] = useState(0);
  const [clipPreviewVersion, setClipPreviewVersion] = useState(0);
  const [selectedClipId, setSelectedClipId] = useState<number | null>(null);
  const [clipDraft, setClipDraft] = useState<Partial<MaterialMixClip>>({});
  const [clipPreviewMode, setClipPreviewMode] = useState<"start" | "end" | null>(null);
  const [clipPreviewError, setClipPreviewError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const timelinePreviewRef = useRef<HTMLVideoElement | null>(null);
  const clipPreviewRef = useRef<HTMLVideoElement | null>(null);

  const filteredSegments = props.segments.filter((segment) => (
    !query.trim()
    || `${segment.text} ${segment.video_name} ${segment.semantic_type} ${segment.position_type}`.toLowerCase().includes(query.trim().toLowerCase())
  ));
  const clips = selectedTimeline?.clips ?? [];
  const selectedClip = clips.find((clip) => clip.clip_id === selectedClipId) ?? null;
  const selectedVoiceAsset = voiceAssets.find((asset) => String(asset.id) === voiceAssetId);
  const selectedBgmAsset = bgmAssets.find((asset) => String(asset.id) === bgmAssetId);
  const selectedVoiceLoudness = assetInputLoudness(selectedVoiceAsset);
  const selectedBgmLoudness = assetInputLoudness(selectedBgmAsset);
  const exportAudioHints = [
    selectedVoiceAsset && selectedVoiceLoudness === null ? "配音素材还没有响度分析，建议先到“配音/BGM”页面分析后再导出。" : "",
    selectedBgmAsset && selectedBgmLoudness === null ? "BGM 还没有响度分析，建议先到“配音/BGM”页面分析后再混音。" : "",
    selectedBgmLoudness !== null && selectedBgmLoudness > -12 ? "当前 BGM 响度偏高，导出会做统一响度，但建议试听确认口播不会被盖住。" : "",
    selectedVoiceLoudness !== null && selectedVoiceLoudness < -24 ? "当前配音响度偏低，建议重新生成或导出时保持统一响度开启。" : "",
  ].filter(Boolean);
  const audioMixRecommendation = selectedVoiceAsset
    ? selectedBgmAsset
      ? "推荐：配音替换原音频 + BGM 混音 + 统一响度 -14 LUFS。"
      : "推荐：配音替换原音频 + 统一响度 -14 LUFS。"
    : selectedBgmAsset
      ? "推荐：保留原音频 + BGM 混音 + 统一响度 -14 LUFS。"
      : "推荐：保留原音频；如原素材音量不稳，开启统一响度。";
  const previewSource = selectedTimelineId && clips.length > 0
    ? `${API_BASE_URL}/material-mix/timelines/${selectedTimelineId}/preview?v=${previewVersion}`
    : "";
  const clipPreviewSource = selectedTimelineId && selectedClip
    ? `${API_BASE_URL}/material-mix/timelines/${selectedTimelineId}/clips/${selectedClip.clip_id}/preview?v=${clipPreviewVersion}`
    : "";

  useEffect(() => {
    void loadTimelines();
    void loadExportAssets();
  }, [props.project.id]);

  useEffect(() => {
    if (!selectedTimeline) return;
    setAudioPolicy(selectedTimeline.audio_policy || "keep_original");
    setVoiceAssetId(selectedTimeline.voice_asset_id ? String(selectedTimeline.voice_asset_id) : "");
    setBgmAssetId(selectedTimeline.bgm_asset_id ? String(selectedTimeline.bgm_asset_id) : "");
    setSubtitlePresetId(selectedTimeline.subtitle_preset_id ? String(selectedTimeline.subtitle_preset_id) : "");
    setNormalizeLoudness(Boolean(selectedTimeline.normalize_loudness));
    setTargetLufs(Number(selectedTimeline.target_lufs ?? -14));
    setBurnSubtitles(Boolean(selectedTimeline.burn_subtitles));
  }, [selectedTimeline?.id]);

  useEffect(() => {
    if (!selectedTimelineId) {
      setSelectedTimeline(null);
      setSelectedClipId(null);
      return;
    }
    void loadTimeline(selectedTimelineId);
  }, [selectedTimelineId]);

  useEffect(() => {
    if (!selectedClip) {
      setClipDraft({});
      return;
    }
    setClipDraft(selectedClip);
    const video = timelinePreviewRef.current;
    if (video && previewSource) {
      video.pause();
      video.currentTime = Math.max(0, selectedClip.timeline_in);
    }
  }, [selectedClip?.clip_id, selectedClip?.timeline_in]);

  useEffect(() => {
    const video = clipPreviewRef.current;
    setClipPreviewError("");
    if (!video || !selectedClip) return;
    video.pause();
    video.currentTime = 0;
    setClipPreviewMode(null);
  }, [selectedClip?.clip_id, clipPreviewSource]);

  async function loadTimelines(nextSelectedId?: number | null) {
    try {
      const data = await api<MaterialMixTimeline[]>(`/material-mix/timelines?project_id=${props.project.id}`);
      setTimelines(data);
      const selectedId = nextSelectedId !== undefined
        ? nextSelectedId
        : (selectedTimelineId && data.some((timeline) => timeline.id === selectedTimelineId) ? selectedTimelineId : data[0]?.id ?? null);
      setSelectedTimelineId(selectedId);
      if (selectedId) {
        await loadTimeline(selectedId);
      } else {
        setSelectedTimeline(null);
      }
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "素材混剪列表加载失败");
    }
  }

  async function loadExportAssets() {
    try {
      const [voices, bgms, subtitles] = await Promise.all([
        api<Asset[]>(`/projects/${props.project.id}/assets?asset_type=voice`),
        api<Asset[]>(`/projects/${props.project.id}/assets?asset_type=bgm`),
        api<Asset[]>(`/projects/${props.project.id}/assets?asset_type=subtitle_preset`),
      ]);
      setVoiceAssets(voices);
      setBgmAssets(bgms);
      setSubtitleAssets(subtitles);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "导出素材加载失败");
    }
  }

  async function patchTimeline(timelineId: number, body: Partial<Pick<MaterialMixTimeline, "name" | "is_favorite">>) {
    try {
      const timeline = await api<MaterialMixTimeline>(`/material-mix/timelines/${timelineId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (timelineId === selectedTimelineId) {
        setSelectedTimeline(timeline);
      }
      setRenamingTimelineId(null);
      await loadTimelines(timeline.id);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "更新时间线草稿失败");
    }
  }

  async function duplicateTimeline(timelineId: number) {
    try {
      const timeline = await api<MaterialMixTimeline>(`/material-mix/timelines/${timelineId}/duplicate`, { method: "POST" });
      setGenerationWarnings([]);
      setGenerationNotes({});
      setReplacementClipId(null);
      setSelectedClipId(timeline.clips?.[0]?.clip_id ?? null);
      props.setMessage(`已复制草稿：${timeline.name}`);
      await loadTimelines(timeline.id);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "复制时间线草稿失败");
    }
  }

  async function deleteTimeline(timelineId: number) {
    const timeline = timelines.find((item) => item.id === timelineId);
    if (!window.confirm(`确定删除素材混剪草稿「${timeline?.name ?? timelineId}」吗？这只会删除草稿和时间线片段，不会删除素材库内容。`)) {
      return;
    }
    try {
      await api(`/material-mix/timelines/${timelineId}`, { method: "DELETE" });
      const nextTimeline = timelines.find((item) => item.id !== timelineId) ?? null;
      if (selectedTimelineId === timelineId) {
        setSelectedTimeline(null);
        setSelectedClipId(null);
        setGenerationWarnings([]);
        setGenerationNotes({});
        setReplacementClipId(null);
      }
      props.setMessage("已删除素材混剪草稿。");
      await loadTimelines(nextTimeline?.id ?? null);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "删除时间线草稿失败");
    }
  }

  function startRenameTimeline(timeline: MaterialMixTimeline) {
    setRenamingTimelineId(timeline.id);
    setRenameTimelineValue(timeline.name);
  }

  async function loadTimeline(timelineId: number) {
    try {
      const timeline = await api<MaterialMixTimeline>(`/material-mix/timelines/${timelineId}`);
      setSelectedTimeline(timeline);
      setGenerationNotes(Object.fromEntries((timeline.clips ?? []).map((clip) => [clip.clip_id, clip.selection_note || "手动加入或历史片段"])));
      setPreviewVersion((current) => current + 1);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "素材混剪详情加载失败");
    }
  }

  async function createTimeline() {
    try {
      const timeline = await api<MaterialMixTimeline>("/material-mix/timelines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: props.project.id, name: newTimelineName.trim() || "素材混剪方案" }),
      });
      props.setMessage("已创建素材混剪时间线。");
      await loadTimelines(timeline.id);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "创建素材混剪失败");
    }
  }

  async function generateTimeline() {
    if (props.segments.length === 0) {
      props.setError("当前项目还没有可用语义片段，请先完成导入分析或在素材库里完成切片。");
      return;
    }
    setGenerating(true);
    setGenerationWarnings([]);
    try {
      const timeline = await api<MaterialMixTimeline>("/material-mix/timelines/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: props.project.id,
          requirement_prompt: generationPrompt,
          target_clip_count: targetClipCount,
          prefer_distinct_sources: preferDistinctSources,
        }),
      });
      setSelectedTimeline(timeline);
      setSelectedTimelineId(timeline.id);
      setSelectedClipId(timeline.clips?.[0]?.clip_id ?? null);
      setGenerationWarnings(timeline.generation_warnings ?? []);
      setGenerationNotes(Object.fromEntries(Object.entries(timeline.generation_notes ?? {}).map(([key, value]) => [Number(key), value])));
      setReplacementClipId(null);
      setPreviewVersion((current) => current + 1);
      setClipPreviewVersion((current) => current + 1);
      await loadTimelines(timeline.id);
      props.setMessage(`已自动生成素材混剪时间线：${timeline.name}`);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "自动生成时间线失败");
    } finally {
      setGenerating(false);
    }
  }

  async function addClip(segmentId: number) {
    if (!selectedTimelineId) {
      props.setError("请先创建或选择一条素材混剪时间线。");
      return;
    }
    try {
      const timeline = await api<MaterialMixTimeline>(`/material-mix/timelines/${selectedTimelineId}/clips`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ segment_id: segmentId, selection_note: "用户手动加入时间线" }),
      });
      setSelectedTimeline(timeline);
      setSelectedClipId(timeline.clips?.at(-1)?.clip_id ?? null);
      setReplacementClipId(null);
      setPreviewVersion((current) => current + 1);
      setClipPreviewVersion((current) => current + 1);
      await loadTimelines(timeline.id);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "添加片段失败");
    }
  }

  async function patchClip(clipId: number, action: "move_up" | "move_down") {
    if (!selectedTimelineId) return;
    try {
      const timeline = await api<MaterialMixTimeline>(`/material-mix/timelines/${selectedTimelineId}/clips/${clipId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      setSelectedTimeline(timeline);
      if (selectedClipId && !timeline.clips?.some((clip) => clip.clip_id === selectedClipId)) {
        setSelectedClipId(timeline.clips?.[0]?.clip_id ?? null);
      }
      setReplacementClipId(null);
      setPreviewVersion((current) => current + 1);
      setClipPreviewVersion((current) => current + 1);
      await loadTimelines(timeline.id);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "调整片段顺序失败");
    }
  }

  async function deleteClip(clipId: number) {
    if (!selectedTimelineId) return;
    try {
      const timeline = await api<MaterialMixTimeline>(`/material-mix/timelines/${selectedTimelineId}/clips/${clipId}`, { method: "DELETE" });
      setSelectedTimeline(timeline);
      if (selectedClipId === clipId) {
        setSelectedClipId(timeline.clips?.[0]?.clip_id ?? null);
      }
      setReplacementClipId(null);
      setPreviewVersion((current) => current + 1);
      setClipPreviewVersion((current) => current + 1);
      await loadTimelines(timeline.id);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "删除时间线片段失败");
    }
  }

  async function exportTimeline() {
    if (!selectedTimelineId) {
      props.setError("请先选择一条时间线。");
      return;
    }
    setExporting(true);
    try {
      const result = await api<{ export_path: string }>(`/material-mix/timelines/${selectedTimelineId}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          output_dir: outputDir || undefined,
          audio_policy: audioPolicy,
          voice_asset_id: voiceAssetId ? Number(voiceAssetId) : undefined,
          bgm_asset_id: bgmAssetId ? Number(bgmAssetId) : undefined,
          subtitle_preset_id: subtitlePresetId ? Number(subtitlePresetId) : undefined,
          normalize_loudness: normalizeLoudness,
          target_lufs: targetLufs,
          burn_subtitles: burnSubtitles,
        }),
      });
      props.setMessage(`素材混剪已导出：${result.export_path}`);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "素材混剪导出失败");
    } finally {
      setExporting(false);
    }
  }

  function applyAudioMixRecommendation() {
    if (selectedVoiceAsset) {
      setAudioPolicy(selectedBgmAsset ? "replace_with_voice" : "replace_with_voice");
      setNormalizeLoudness(true);
      setTargetLufs(-14);
      props.setMessage("已应用推荐音频策略：配音优先，并开启统一响度。");
      return;
    }
    if (selectedBgmAsset) {
      setAudioPolicy("keep_original");
      setNormalizeLoudness(true);
      setTargetLufs(-14);
      props.setMessage("已应用推荐音频策略：保留原音频、叠加 BGM，并统一响度。");
      return;
    }
    setAudioPolicy("keep_original");
    setNormalizeLoudness(true);
    setTargetLufs(-14);
    props.setMessage("已应用推荐音频策略：保留原音频，并开启统一响度。");
  }

  async function chooseOutputDir() {
    if (!window.electronAPI?.selectExportDirectory) {
      props.setError("当前窗口没有连接到系统文件夹选择器，请重启软件后再试。");
      return;
    }
    try {
      const selectedPath = await window.electronAPI.selectExportDirectory();
      if (selectedPath) {
        setOutputDir(selectedPath);
      }
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "选择保存路径失败");
    }
  }

  async function updateClipTiming(values: Partial<Pick<MaterialMixClip, "source_in" | "source_out">>, mode: "start" | "end" | null = null) {
    if (!selectedTimelineId || !selectedClip) return;
    const nextIn = Number(values.source_in ?? selectedClip.source_in);
    const nextOut = Number(values.source_out ?? selectedClip.source_out);
    if (nextOut <= nextIn) {
      props.setError("片段结束时间必须大于开始时间。");
      return;
    }
    if (nextOut - nextIn < 0.3) {
      props.setError("时间线片段至少保留 0.3 秒。");
      return;
    }
    try {
      const timeline = await api<MaterialMixTimeline>(`/material-mix/timelines/${selectedTimelineId}/clips/${selectedClip.clip_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      setSelectedTimeline(timeline);
      setSelectedClipId(selectedClip.clip_id);
      setClipPreviewMode(mode);
      setPreviewVersion((current) => current + 1);
      setClipPreviewVersion((current) => current + 1);
      await loadTimelines(timeline.id);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "片段出入点保存失败");
    }
  }

  async function replaceClip(clip: MaterialMixClip, segment: Segment, selectionReason = "") {
    if (!selectedTimelineId) return;
    const note = `手动替换为「${splitMultiValue(segment.semantic_type)[0] || segment.semantic_type || "未标注"}」片段`
      + (selectionReason ? `，${selectionReason}` : segment.selling_points ? `，卖点：${splitMultiValue(segment.selling_points).slice(0, 3).join(" / ")}` : "");
    try {
      const timeline = await api<MaterialMixTimeline>(`/material-mix/timelines/${selectedTimelineId}/clips/${clip.clip_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ segment_id: segment.id, selection_note: note }),
      });
      setSelectedTimeline(timeline);
      setSelectedClipId(clip.clip_id);
      setReplacementClipId(null);
      setGenerationNotes((current) => ({
        ...current,
        [clip.clip_id]: note,
      }));
      setClipPreviewMode(null);
      setPreviewVersion((current) => current + 1);
      setClipPreviewVersion((current) => current + 1);
      await loadTimelines(timeline.id);
      window.setTimeout(() => {
        const nextClip = timeline.clips?.find((item) => item.clip_id === clip.clip_id);
        const video = timelinePreviewRef.current;
        if (video && nextClip) {
          video.pause();
          video.currentTime = Math.max(0, nextClip.timeline_in);
        }
      }, 0);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "替换时间线片段失败");
    }
  }

  function getClipReplacementCandidates(clip: MaterialMixClip) {
    const usedSegmentIds = new Set(clips.filter((item) => item.clip_id !== clip.clip_id).map((item) => item.segment_id));
    const scored = props.segments
      .filter((segment) => segment.id !== clip.segment_id)
      .map((segment) => {
        const sameSemantic = multiValuesOverlap(segment.semantic_type, clip.semantic_type);
        const samePosition = multiValuesOverlap(segment.position_type, clip.position_type);
        const sameSellingPoint = multiValuesOverlap(segment.selling_points ?? "", clip.selling_points ?? "");
        const sameVisualTag = multiValuesOverlap(segment.visual_tags ?? "", clip.visual_tags ?? "");
        const unused = !usedSegmentIds.has(segment.id);
        const distinctSource = segment.video_name !== clip.video_name;
        const durationGap = Math.abs((segment.end_seconds - segment.start_seconds) - (clip.timeline_out - clip.timeline_in));
        const durationFit = durationGap < 1.2;
        const score = (sameSemantic ? 100 : 0) + (samePosition ? 30 : 0) + (sameSellingPoint ? 26 : 0) + (sameVisualTag ? 18 : 0) + (distinctSource ? 12 : 0) + (unused ? 8 : 0) + (durationFit ? 6 : 0);
        const reasons = [
          sameSemantic ? "同语义" : "",
          samePosition ? "同位置" : "",
          sameSellingPoint ? "卖点命中" : "",
          sameVisualTag ? "画面命中" : "",
          distinctSource ? "来源分散" : "",
          unused ? "未使用" : "",
          durationFit ? "时长接近" : "",
        ].filter(Boolean);
        return { segment, score, sameSemantic, samePosition, sameSellingPoint, sameVisualTag, reasons };
      })
      .sort((left, right) => right.score - left.score || left.segment.video_name.localeCompare(right.segment.video_name) || left.segment.start_seconds - right.segment.start_seconds);
    return scored;
  }

  function nudgeClip(boundary: "start" | "end", delta: number) {
    if (!selectedClip) return;
    const value = boundary === "start"
      ? Math.max(0, Number((selectedClip.source_in + delta).toFixed(1)))
      : Math.max(0, Number((selectedClip.source_out + delta).toFixed(1)));
    void updateClipTiming(boundary === "start" ? { source_in: value } : { source_out: value }, boundary);
  }

  function saveClipDraft() {
    if (!selectedClip) return;
    void updateClipTiming({
      source_in: Number(clipDraft.source_in ?? selectedClip.source_in),
      source_out: Number(clipDraft.source_out ?? selectedClip.source_out),
    });
  }

  function handleClipPreviewLoaded() {
    const video = clipPreviewRef.current;
    if (!video) return;
    if (clipPreviewMode === "end") {
      video.currentTime = Math.max(0, video.duration - 0.8);
      void video.play().catch(() => undefined);
      return;
    }
    if (clipPreviewMode === "start") {
      video.currentTime = 0;
      void video.play().catch(() => undefined);
      return;
    }
    video.currentTime = 0;
    video.pause();
  }

  function handleClipPreviewTimeUpdate() {
    const video = clipPreviewRef.current;
    if (!video || !clipPreviewMode) return;
    const stopAt = clipPreviewMode === "end" ? Math.max(0, video.duration - 0.05) : Math.min(video.duration, 0.8);
    if (video.currentTime >= stopAt) {
      video.pause();
      video.currentTime = stopAt;
      setClipPreviewMode(null);
    }
  }

  function selectTimelineClip(clip: MaterialMixClip) {
    setSelectedClipId(clip.clip_id);
    const video = timelinePreviewRef.current;
    if (video) {
      video.pause();
      video.currentTime = Math.max(0, clip.timeline_in);
    }
  }

  return (
    <section className="material-mix-page material-mix-redesign">
      <div className="view-sticky-head material-mix-head material-mix-toolbar">
        <div className="section-title material-toolbar-title">
          <div>
            <h2>素材混剪</h2>
            <p>先选草稿，再调时间线，右侧看预览和微调。</p>
          </div>
          <div className="timeline-total">
            <span>总时长</span>
            <strong>{(selectedTimeline?.duration_seconds ?? 0).toFixed(1)}s</strong>
          </div>
        </div>
        <div className="material-toolbar-grid">
          <label className="material-toolbar-prompt">混剪需求
            <input
              onChange={(event) => setGenerationPrompt(event.target.value)}
              placeholder="例如：30秒左右，节奏快，开头抓人，结尾强促单"
              value={generationPrompt}
            />
          </label>
          <label>片段数
            <input max={30} min={3} onChange={(event) => setTargetClipCount(Number(event.target.value))} type="number" value={targetClipCount} />
          </label>
          <label className="checkbox-line compact-check">
            <input checked={preferDistinctSources} onChange={(event) => setPreferDistinctSources(event.target.checked)} type="checkbox" />
            不同来源
          </label>
          <button className="primary-action" disabled={generating || props.segments.length === 0} onClick={generateTimeline}>
            {generating ? "生成中..." : "自动生成"}
          </button>
          <label>新草稿
            <input value={newTimelineName} onChange={(event) => setNewTimelineName(event.target.value)} />
          </label>
          <button className="secondary" onClick={createTimeline}>创建空草稿</button>
          <button className="secondary" onClick={() => setShowSegmentPicker(true)}>添加片段</button>
          <button className="secondary" onClick={chooseOutputDir}>保存路径</button>
          <button className="primary-action" disabled={!selectedTimelineId || clips.length === 0 || exporting} onClick={exportTimeline}>
            {exporting ? "导出中..." : "导出"}
          </button>
        </div>
        <div className="material-toolbar-grid export-options-grid">
          <div className="audio-recommendation">
            <span>{audioMixRecommendation}</span>
            <button className="ghost-button" onClick={applyAudioMixRecommendation}>应用推荐</button>
          </div>
          <label>原音频策略
            <select value={audioPolicy} onChange={(event) => setAudioPolicy(event.target.value)}>
              <option value="keep_original">保留原音频</option>
              <option value="remove_original">移除原音频</option>
              <option value="enhance_voice">保留人声增强轨</option>
              <option value="replace_with_voice">替换为配音</option>
              <option value="voice_over">原音频叠加配音</option>
            </select>
          </label>
          <label>配音素材
            <select value={voiceAssetId} onChange={(event) => setVoiceAssetId(event.target.value)}>
              <option value="">不使用配音</option>
              {voiceAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
            </select>
            {selectedVoiceLoudness !== null && <span className="field-hint">已分析：{selectedVoiceLoudness.toFixed(1)} LUFS</span>}
          </label>
          <label>BGM
            <select value={bgmAssetId} onChange={(event) => setBgmAssetId(event.target.value)}>
              <option value="">不加 BGM</option>
              {bgmAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
            </select>
            {selectedBgmLoudness !== null && <span className="field-hint">已分析：{selectedBgmLoudness.toFixed(1)} LUFS</span>}
          </label>
          <label className="checkbox-line compact-check">
            <input checked={normalizeLoudness} onChange={(event) => setNormalizeLoudness(event.target.checked)} type="checkbox" />
            统一响度
          </label>
          <label>目标 LUFS
            <input max={-8} min={-24} step={1} type="number" value={targetLufs} onChange={(event) => setTargetLufs(Number(event.target.value))} />
          </label>
          <label className="checkbox-line compact-check">
            <input checked={burnSubtitles} onChange={(event) => setBurnSubtitles(event.target.checked)} type="checkbox" />
            一键字幕
          </label>
          <label>字幕预设
            <select value={subtitlePresetId} onChange={(event) => setSubtitlePresetId(event.target.value)}>
              <option value="">内置字幕</option>
              {subtitleAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
            </select>
          </label>
        </div>
        {generationWarnings.length > 0 && (
          <div className="material-warning-list">
            {generationWarnings.map((warning) => <span key={warning}>{warning}</span>)}
          </div>
        )}
        {exportAudioHints.length > 0 && (
          <div className="material-warning-list">
            {exportAudioHints.map((hint) => <span key={hint}>{hint}</span>)}
          </div>
        )}
        <p className="material-output-dir">{outputDir || "未选择时默认保存到 data/exports"}</p>
      </div>

      <div className="material-mix-layout material-three-column">
        <aside className="panel timeline-draft-sidebar">
          <div className="section-title compact-title">
            <div>
              <h2>草稿</h2>
              <p>{timelines.length} 条时间线</p>
            </div>
          </div>
          <div className="timeline-draft-list">
            {timelines.map((timeline) => {
              const isFavorite = Boolean(timeline.is_favorite);
              const isRenaming = renamingTimelineId === timeline.id;
              return (
                <article className={selectedTimelineId === timeline.id ? "timeline-draft-card active" : "timeline-draft-card"} key={timeline.id}>
                  <button className="draft-main" onClick={() => { setGenerationWarnings([]); setGenerationNotes({}); setReplacementClipId(null); setSelectedTimelineId(timeline.id); }}>
                    <span className={isFavorite ? "favorite-star active" : "favorite-star"}>★</span>
                    <span>
                      <strong>{timeline.name}</strong>
                      <small>{(timeline.duration_seconds ?? 0).toFixed(1)}s · {timeline.clip_count ?? 0}段</small>
                    </span>
                  </button>
                  {isRenaming ? (
                    <div className="draft-rename">
                      <input value={renameTimelineValue} onChange={(event) => setRenameTimelineValue(event.target.value)} />
                      <button className="ghost-button" onClick={() => patchTimeline(timeline.id, { name: renameTimelineValue })}>保存</button>
                      <button className="ghost-button" onClick={() => setRenamingTimelineId(null)}>取消</button>
                    </div>
                  ) : (
                    <div className="draft-actions">
                      <button className="ghost-button" onClick={() => patchTimeline(timeline.id, { is_favorite: !isFavorite })}>{isFavorite ? "取消推荐" : "推荐"}</button>
                      <button className="ghost-button" onClick={() => startRenameTimeline(timeline)}>重命名</button>
                      <button className="ghost-button" onClick={() => duplicateTimeline(timeline.id)}>复制</button>
                      <button className="danger-action" onClick={() => deleteTimeline(timeline.id)}>删除</button>
                    </div>
                  )}
                </article>
              );
            })}
            {timelines.length === 0 && <p className="empty timeline-draft-empty">还没有草稿。可以自动生成，或创建空草稿后添加片段。</p>}
          </div>
        </aside>

        <section className="panel material-timeline-panel material-timeline-main">
          <div className="section-title compact-title">
            <div>
              <h2>{selectedTimeline?.name ?? "时间线"}</h2>
              <p>{clips.length} 个片段 · 单视频轨</p>
            </div>
            <button className="secondary" onClick={() => setShowSegmentPicker(true)}>添加片段</button>
          </div>
          <div className="timeline-clip-list">
            {clips.map((clip, index) => {
              const replacementCandidates = getClipReplacementCandidates(clip);
              const hasExactCandidates = replacementCandidates.some((item) => item.sameSemantic && item.samePosition);
              return (
                <article
                  className={clip.clip_id === selectedClipId ? "timeline-clip-card active" : "timeline-clip-card"}
                  key={clip.clip_id}
                  onClick={() => selectTimelineClip(clip)}
                >
                  <span className="timeline-position">#{clip.position}</span>
                  <div>
                    <div className="timeline-clip-meta">
                      <TagChip tag={splitMultiValue(clip.semantic_type)[0] ?? clip.semantic_type} />
                      <strong>{formatClockPrecise(clip.timeline_in)} - {formatClockPrecise(clip.timeline_out)}</strong>
                      <span>{(clip.timeline_out - clip.timeline_in).toFixed(1)}s</span>
                    </div>
                    <p>{clip.text || "无台词"}</p>
                    <small>{clip.video_name} · 源 {formatClockPrecise(clip.source_in)} - {formatClockPrecise(clip.source_out)}</small>
                    <p className="clip-selection-note">
                      <strong>理由</strong>
                      <span>{clip.selection_note || generationNotes[clip.clip_id] || "手动加入或历史片段"}</span>
                    </p>
                    {replacementClipId === clip.clip_id && (
                      <section className="replacement-panel material-replacement-panel" onClick={(event) => event.stopPropagation()}>
                        <div className="section-title compact-title">
                          <div>
                            <h3>替换片段</h3>
                            <p>{hasExactCandidates ? "同 tag / 同位置候选优先展示" : "没有完全匹配候选，已显示其他可用片段"}</p>
                          </div>
                          <button className="secondary" onClick={() => setReplacementClipId(null)}>收起</button>
                        </div>
                        <div className="replacement-list">
                          {replacementCandidates.map(({ segment, sameSemantic, samePosition, score, reasons }) => (
                            <button className="replacement-card" key={segment.id} onClick={() => replaceClip(clip, segment, reasons.slice(0, 4).join(" / "))}>
                              <img src={`${API_BASE_URL}/segments/${segment.id}/thumbnail`} />
                              <span>{sameSemantic ? "同内容" : "其他内容"} · {samePosition ? "同位置" : "其他位置"} · {(segment.end_seconds - segment.start_seconds).toFixed(1)}s</span>
                              <div className="candidate-score-line">
                                <strong>{score}</strong>
                                <small>{reasons.slice(0, 4).join(" / ") || "补充候选"}</small>
                              </div>
                              <div className="segment-type-line">{splitMultiValue(segment.semantic_type).map((tag) => <TagChip key={tag} tag={tag} />)}</div>
                              {(segment.selling_points || segment.visual_tags) && (
                                <div className="segment-type-line">
                                  {[...splitMultiValue(segment.selling_points), ...splitMultiValue(segment.visual_tags)].slice(0, 4).map((tag) => <span className="tag-chip tag-color-default" key={tag}>{tag}</span>)}
                                </div>
                              )}
                              <strong>{segment.text.slice(0, 52) || `片段 #${segment.id}`}</strong>
                              <small>{segment.video_name}</small>
                            </button>
                          ))}
                          {replacementCandidates.length === 0 && <p className="empty">当前项目没有其他可替换片段。</p>}
                        </div>
                      </section>
                    )}
                  </div>
                  <div className="timeline-actions" onClick={(event) => event.stopPropagation()}>
                    <button className="ghost-button" disabled={index === 0} onClick={() => patchClip(clip.clip_id, "move_up")}>上移</button>
                    <button className="ghost-button" disabled={index === clips.length - 1} onClick={() => patchClip(clip.clip_id, "move_down")}>下移</button>
                    <button className="ghost-button" onClick={() => { setSelectedClipId(clip.clip_id); setReplacementClipId(replacementClipId === clip.clip_id ? null : clip.clip_id); }}>替换</button>
                    <button className="danger-action" onClick={() => deleteClip(clip.clip_id)}>删除</button>
                  </div>
                </article>
              );
            })}
            {clips.length === 0 && <p className="empty timeline-empty">当前草稿还没有片段。点击“添加片段”或“自动生成”。</p>}
          </div>
        </section>

        <aside className="panel material-preview-sidebar">
          <div className="section-title compact-title">
            <div>
              <h2>预览与微调</h2>
              <p>{selectedClip ? `当前 #${selectedClip.position}` : "选择分镜后微调"}</p>
            </div>
          </div>
          <div className="material-preview-box">
            {previewSource ? (
              <video
                key={previewSource}
                ref={timelinePreviewRef}
                src={previewSource}
                controls
                preload="metadata"
                onError={() => props.setError("素材混剪预览生成失败，可检查时间线是否为空或源视频是否还存在。")}
              />
            ) : (
              <div className="material-preview-empty">
                <strong>暂无预览</strong>
                <span>从左侧添加片段后可预览和导出。</span>
              </div>
            )}
          </div>
          <div className="clip-trim-panel">
            {selectedClip ? (
              <>
                <div className="section-title compact-title">
                  <div>
                    <h2>当前片段微调</h2>
                    <p>{selectedClip.video_name}</p>
                  </div>
                  <button className="primary-action" onClick={saveClipDraft}>保存</button>
                </div>
                <div className="material-clip-preview">
                  <video
                    key={clipPreviewSource}
                    ref={clipPreviewRef}
                    src={clipPreviewSource}
                    controls
                    preload="metadata"
                    onLoadedMetadata={handleClipPreviewLoaded}
                    onTimeUpdate={handleClipPreviewTimeUpdate}
                    onError={() => setClipPreviewError("单段预览暂时不可用，不影响完整成片预览和导出。")}
                  />
                  {clipPreviewError && <p className="inline-preview-error">{clipPreviewError}</p>}
                </div>
                <div className="micro-controls">
                  <button onClick={() => nudgeClip("start", -0.1)}>入-</button>
                  <button onClick={() => nudgeClip("start", 0.1)}>入+</button>
                  <button onClick={() => nudgeClip("end", -0.1)}>出-</button>
                  <button onClick={() => nudgeClip("end", 0.1)}>出+</button>
                </div>
                <div className="edit-grid compact">
                  <label>开始秒
                    <input type="number" step="0.1" value={clipDraft.source_in ?? selectedClip.source_in} onChange={(event) => setClipDraft((current) => ({ ...current, source_in: Number(event.target.value) }))} />
                  </label>
                  <label>结束秒
                    <input type="number" step="0.1" value={clipDraft.source_out ?? selectedClip.source_out} onChange={(event) => setClipDraft((current) => ({ ...current, source_out: Number(event.target.value) }))} />
                  </label>
                </div>
                <p className="clip-trim-caption">
                  时间线 {formatClockPrecise(selectedClip.timeline_in)} - {formatClockPrecise(selectedClip.timeline_out)}
                </p>
              </>
            ) : (
              <p className="empty timeline-empty">选择时间线片段后可微调出入点。</p>
            )}
          </div>
        </aside>
      </div>
      {showSegmentPicker && (
        <div className="segment-drawer-backdrop" onClick={() => setShowSegmentPicker(false)}>
          <aside className="segment-drawer panel" onClick={(event) => event.stopPropagation()}>
            <div className="section-title compact-title">
              <div>
                <h2>添加片段</h2>
                <p>{filteredSegments.length} / {props.segments.length} 个片段</p>
              </div>
              <button className="secondary" onClick={() => setShowSegmentPicker(false)}>关闭</button>
            </div>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索台词、来源或 tag..." />
            <div className="material-segment-list drawer-segment-list">
              {filteredSegments.map((segment) => (
                <article className="material-segment-row" key={segment.id}>
                  <img src={`${API_BASE_URL}/segments/${segment.id}/thumbnail`} />
                  <div>
                    <div className="segment-type-line">{splitMultiValue(segment.semantic_type).map((tag) => <TagChip key={tag} tag={tag} />)}</div>
                    <strong>{formatClockPrecise(segment.start_seconds)} - {formatClockPrecise(segment.end_seconds)}</strong>
                    <p>{segment.text || "无台词"}</p>
                    <small>{segment.video_name}</small>
                  </div>
                  <button className="secondary" onClick={() => addClip(segment.id)}>添加</button>
                </article>
              ))}
              {props.segments.length === 0 && <p className="empty material-empty-note">还没有可用语义片段，请先在“导入分析”完成视频转录和切片。</p>}
              {props.segments.length > 0 && filteredSegments.length === 0 && <p className="empty">没有匹配搜索条件的片段。</p>}
            </div>
          </aside>
        </div>
      )}
    </section>
  );
}

function SegmentLibrary(props: { segments: Segment[]; videos: VideoItem[]; onRefresh: () => void; setError: (value: string) => void; setMessage: (value: string) => void }) {
  useCloseTagMenusOnOutsideClick();
  const [libraryGroup, setLibraryGroup] = useState<"finished" | "loose">("finished");
  const [tagFilters, setTagFilters] = useState<string[]>([]);
  const [position, setPosition] = useState("");
  const [query, setQuery] = useState("");
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [sortMode, setSortMode] = useState<"time" | "duration">("time");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedForExport, setSelectedForExport] = useState<number[]>([]);
  const [exportDir, setExportDir] = useState("");
  const [draft, setDraft] = useState<Partial<Segment>>({});
  const [previewVersion, setPreviewVersion] = useState(0);
  const [previewMode, setPreviewMode] = useState<"start" | "end" | null>(null);
  const [deduping, setDeduping] = useState(false);
  const [splitTarget, setSplitTarget] = useState<Segment | null>(null);
  const previewRef = useRef<HTMLVideoElement | null>(null);
  const selectedPreviewAutoplayRef = useRef(false);
  useVideoKeyboardShortcuts(previewRef, !splitTarget);
  const groupSegments = props.segments.filter((segment) => (
    libraryGroup === "loose"
      ? String(segment.source_mode || "") === "product_assets"
      : String(segment.source_mode || "") !== "product_assets"
  ));
  const finishedCount = props.segments.filter((segment) => String(segment.source_mode || "") !== "product_assets").length;
  const looseCount = props.segments.filter((segment) => String(segment.source_mode || "") === "product_assets").length;
  const filtered = groupSegments
    .filter((segment) => (tagFilters.length === 0 || tagFilters.some((tag) => multiValueIncludes(segment.semantic_type, tag))) && (!position || multiValueIncludes(segment.position_type, position)))
    .filter((segment) => !query.trim() || `${segment.text} ${segment.video_name} ${segment.semantic_type} ${segment.selling_points ?? ""} ${segment.visual_tags ?? ""} ${segment.visual_description ?? ""}`.toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a, b) => {
      if (sortMode === "duration") return (b.end_seconds - b.start_seconds) - (a.end_seconds - a.start_seconds);
      return a.video_name.localeCompare(b.video_name) || a.start_seconds - b.start_seconds;
    });
  const selected = groupSegments.find((segment) => segment.id === selectedId) ?? filtered[0] ?? null;
  const tagCounts = SEGMENT_TYPES.map((tag) => ({
    tag,
    count: groupSegments.filter((segment) => multiValueIncludes(segment.semantic_type, tag)).length,
  }));
  const exportTagGroups = Array.from(groupSegments.reduce<Map<string, { tag: string; kind: string; segments: Segment[] }>>((groups, segment) => {
    [
      ...splitMultiValue(segment.semantic_type).map((tag) => ({ tag, kind: "语义" })),
      ...splitMultiValue(segment.selling_points).map((tag) => ({ tag, kind: "卖点" })),
      ...splitMultiValue(segment.visual_tags).map((tag) => ({ tag, kind: "画面" })),
    ].forEach(({ tag, kind }) => {
      const key = `${kind}:${tag}`;
      const group = groups.get(key) ?? { tag, kind, segments: [] };
      group.segments.push(segment);
      groups.set(key, group);
    });
    return groups;
  }, new Map()).values()).sort((left, right) => right.segments.length - left.segments.length || left.tag.localeCompare(right.tag)).slice(0, 18);
  const groupedSegments = filtered.reduce<Record<string, Segment[]>>((groups, segment) => {
    groups[segment.video_name] = groups[segment.video_name] ?? [];
    groups[segment.video_name].push(segment);
    return groups;
  }, {});
  const selectedVideo = selected ? props.videos.find((video) => video.id === selected.video_id) : null;
  const previewOrientation = selectedVideo && selectedVideo.height > selectedVideo.width ? "portrait" : "landscape";

  useEffect(() => {
    if (!selected) {
      setSelectedId(null);
      setDraft({});
      return;
    }
    if (selected.id !== selectedId) {
      setSelectedId(selected.id);
    }
    setDraft(selected);
  }, [selected?.id]);

  useEffect(() => {
    const video = previewRef.current;
    if (!video || !selected) return;
    setPreviewMode(null);
    video.currentTime = 0;
    if (selectedPreviewAutoplayRef.current) {
      void video.play().catch(() => undefined);
    } else {
      video.pause();
    }
  }, [selected?.id]);

  function isPreviewAtEnd(video: HTMLVideoElement) {
    return video.duration > 0 && video.currentTime >= video.duration - 0.12;
  }

  function handlePreviewLoaded() {
    const video = previewRef.current;
    if (!video) return;
    if (!previewMode) {
      video.currentTime = 0;
      if (selectedPreviewAutoplayRef.current) {
        selectedPreviewAutoplayRef.current = false;
        void video.play().catch(() => undefined);
      } else {
        video.pause();
      }
      return;
    }
    if (previewMode === "end") {
      video.currentTime = Math.max(0, video.duration - 0.8);
    } else {
      video.currentTime = 0;
    }
    void video.play().catch(() => undefined);
  }

  function handlePreviewTimeUpdate() {
    const video = previewRef.current;
    if (!video || !previewMode) return;
    const stopAt = previewMode === "end" ? Math.max(0, video.duration - 0.05) : Math.min(video.duration, 0.8);
    if (video.currentTime >= stopAt) {
      video.pause();
      video.currentTime = stopAt;
      setPreviewMode(null);
    }
  }

  async function patchSegment(segment: Segment, values: Partial<Segment>, mode: "start" | "end" | null = null) {
    try {
      const updated = await api<Segment>(`/segments/${segment.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      const timingChanged = "start_seconds" in values || "end_seconds" in values;
      setSelectedId(segment.id);
      setDraft(updated);
      if (timingChanged || mode) {
        setPreviewMode(mode);
        setPreviewVersion((current) => current + 1);
      }
      props.setMessage("片段已保存。");
      props.onRefresh();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "片段保存失败");
    }
  }

  async function saveSegment() {
    if (!selected) return;
    await patchSegment(selected, {
      semantic_type: draft.semantic_type,
      position_type: draft.position_type,
      start_seconds: Number(draft.start_seconds ?? selected.start_seconds),
      end_seconds: Number(draft.end_seconds ?? selected.end_seconds),
      selling_points: draft.selling_points ?? selected.selling_points ?? "",
      visual_tags: draft.visual_tags ?? selected.visual_tags ?? "",
    });
  }

  async function nudgeSegment(segment: Segment, boundary: "start" | "end", delta: number) {
    const minDuration = 0.3;
    const nextStart = boundary === "start" ? Math.max(0, Number((segment.start_seconds + delta).toFixed(1))) : segment.start_seconds;
    const nextEnd = boundary === "end" ? Math.max(minDuration, Number((segment.end_seconds + delta).toFixed(1))) : segment.end_seconds;
    if (nextEnd - nextStart < minDuration) {
      props.setError("片段至少保留 0.3 秒。");
      return;
    }
    await patchSegment(segment, { start_seconds: nextStart, end_seconds: nextEnd }, boundary);
  }

  async function chooseExportDir() {
    if (!window.electronAPI?.selectExportDirectory) {
      props.setError("当前窗口没有连接到系统文件夹选择器，请重启软件后再试。");
      return;
    }
    try {
      const selectedPath = await window.electronAPI.selectExportDirectory();
      if (selectedPath) {
        setExportDir(selectedPath);
      }
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "选择保存路径失败");
    }
  }

  function toggleTagFilter(tag: string) {
    setTagFilters((current) => (
      current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag]
    ));
  }

  async function exportSegmentIds(segmentIds: number[], exportTag = "") {
    if (segmentIds.length === 0) {
      props.setError("请先选择要导出的片段。");
      return;
    }
    try {
      const result = await api<{ export_paths: string[]; export_root?: string }>("/segments/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ segment_ids: segmentIds, output_dir: exportDir || undefined, export_tag: exportTag }),
      });
      props.setMessage(`已导出 ${result.export_paths.length} 个素材，已放入${exportTag ? `「${exportTag}」` : "语义 tag"}文件夹：${result.export_root || result.export_paths.join("；")}`);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "导出失败");
    }
  }

  async function deleteSelectedSegments() {
    if (selectedForExport.length === 0) {
      props.setError("请先勾选要删除的片段。");
      return;
    }
    if (!window.confirm(`确定删除选中的 ${selectedForExport.length} 个片段吗？删除后不会再参与后续混剪方案。`)) {
      return;
    }
    try {
      const result = await api<{ removed_count: number }>("/segments", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ segment_ids: selectedForExport }),
      });
      props.setMessage(`已删除 ${result.removed_count} 个片段。`);
      setSelectedForExport([]);
      setSelectedId(null);
      props.onRefresh();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "删除片段失败");
    }
  }

  async function dedupeSegments() {
    setDeduping(true);
    try {
      const result = await api<{ checked_count: number; duplicate_count: number; removed_count: number; errors: Array<{ segment_id: number; error: string }> }>(
        `/projects/${props.segments[0]?.project_id ?? props.videos[0]?.project_id ?? 0}/segments/dedupe`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dry_run: false }),
        },
      );
      props.setMessage(`已检查 ${result.checked_count} 个分镜，移除 ${result.removed_count} 个完全重复片段。${result.errors.length ? ` 有 ${result.errors.length} 个片段无法计算指纹。` : ""}`);
      setSelectedForExport([]);
      setSelectedId(null);
      props.onRefresh();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "重复片段剔除失败");
    } finally {
      setDeduping(false);
    }
  }

  function toggleExportSelection(segmentId: number) {
    setSelectedForExport((current) => (
      current.includes(segmentId) ? current.filter((id) => id !== segmentId) : [...current, segmentId]
    ));
  }

  function selectSegmentForPreview(segment: Segment) {
    selectedPreviewAutoplayRef.current = true;
    if (segment.id === selected?.id) {
      const video = previewRef.current;
      if (video) {
        video.currentTime = 0;
        void video.play().catch(() => undefined);
      }
      return;
    }
    setSelectedId(segment.id);
  }

  async function splitSegment(segment: Segment, cutPoints: number[]) {
    try {
      const result = await api<{ created_segments: Segment[]; removed_segment_id: number; segments: Segment[] }>(`/segments/${segment.id}/split`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cut_points: cutPoints }),
      });
      setSplitTarget(null);
      setSelectedForExport((current) => current.filter((id) => id !== segment.id));
      setSelectedId(result.created_segments[0]?.id ?? null);
      props.setMessage(`已拆分为 ${result.created_segments.length} 个小分镜。`);
      props.onRefresh();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "拆分分镜失败");
    }
  }

  return (
    <>
      <div className="view-sticky-head segment-sticky-head">
        <div className="section-title segment-manager-title">
          <div>
            <h2>素材片段管理</h2>
            <p>筛选、导出、微调、拆分。</p>
          </div>
        </div>
        <section className="segment-source-switch">
          <button
            className={libraryGroup === "finished" ? "active" : ""}
            onClick={() => {
              setLibraryGroup("finished");
              setSelectedId(null);
              setSelectedForExport([]);
            }}
          >
            成片导入分析片段 <strong>{finishedCount}</strong>
          </button>
          <button
            className={libraryGroup === "loose" ? "active" : ""}
            onClick={() => {
              setLibraryGroup("loose");
              setSelectedId(null);
              setSelectedForExport([]);
            }}
          >
            用户导入零散素材 <strong>{looseCount}</strong>
          </button>
        </section>
        <section className="segment-toolbar">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索台词或关键词..." />
          <div className="segmented-control" aria-label="视图">
            <button className={viewMode === "grid" ? "active" : ""} onClick={() => setViewMode("grid")}>网格</button>
            <button className={viewMode === "list" ? "active" : ""} onClick={() => setViewMode("list")}>列表</button>
          </div>
          <label>排序
            <select value={sortMode} onChange={(event) => setSortMode(event.target.value as "time" | "duration")}>
              <option value="time">时间</option>
              <option value="duration">时长</option>
            </select>
          </label>
          <select value={position} onChange={(event) => setPosition(event.target.value)}>
            <option value="">全部位置</option>
            {POSITION_TYPES.map((item) => <option key={item}>{item}</option>)}
          </select>
        </section>

        <section className="tag-filter-strip">
          <button className={tagFilters.length === 0 ? "tag-filter active" : "tag-filter"} onClick={() => setTagFilters([])}>
            全部 {groupSegments.length}
          </button>
          {tagCounts.map(({ tag, count }) => (
            <button
              className={`${tagFilters.includes(tag) ? "tag-filter active" : "tag-filter"} ${tagColorClass(tag)}`}
              disabled={count === 0}
              key={tag}
              onClick={() => toggleTagFilter(tag)}
            >
              {tag} {count}
            </button>
          ))}
        </section>

        {exportTagGroups.length > 0 && (
          <section className="tag-export-strip">
            <span>按 tag 导出</span>
            {exportTagGroups.map((group) => (
              <button
                className="tag-filter"
                key={`${group.kind}:${group.tag}`}
                onClick={() => exportSegmentIds(group.segments.map((segment) => segment.id), group.tag)}
              >
                {group.kind} · {group.tag} {group.segments.length}
              </button>
            ))}
          </section>
        )}

        <section className="export-bar">
          <button className="secondary" onClick={chooseExportDir}>选择保存路径</button>
          <span>{exportDir || "未选择时默认保存到 data/exports"}</span>
          <button className="secondary" disabled={deduping || groupSegments.length === 0} onClick={dedupeSegments}>
            {deduping ? "检测中..." : "剔除重复片段"}
          </button>
          <button className="danger-action" disabled={selectedForExport.length === 0} onClick={deleteSelectedSegments}>
            删除选中 {selectedForExport.length}
          </button>
          <button className="primary-action" disabled={selectedForExport.length === 0} onClick={() => exportSegmentIds(selectedForExport)}>
            批量导出 {selectedForExport.length}
          </button>
          <button className="primary-action" disabled={filtered.length === 0} onClick={() => exportSegmentIds(filtered.map((segment) => segment.id))}>
            全部导出 {filtered.length}
          </button>
        </section>
      </div>

      <section className="segment-workbench">
        <div className="segment-browser">
          <p className="segment-count">{filtered.length} / {groupSegments.length} 个分镜</p>
          {Object.entries(groupedSegments).map(([videoName, videoSegments]) => (
            <section className="video-segment-group" key={videoName}>
              <div className="video-group-title">
                <strong>{videoName}</strong>
                <span>{videoSegments.length} 个分镜</span>
              </div>
              <div className={viewMode === "grid" ? "segment-list grid-view" : "segment-list list-view"}>
                {videoSegments.map((segment, index) => (
                  <SegmentCard
                    active={segment.id === selected?.id}
                    index={index + 1}
                    segment={segment}
                    key={segment.id}
                    viewMode={viewMode}
                    selectedForExport={selectedForExport.includes(segment.id)}
                    onSelect={() => selectSegmentForPreview(segment)}
                    onNudge={nudgeSegment}
                    onTagsChange={(targetSegment, field, values) => patchSegment(targetSegment, { [field]: joinMultiValue(values) })}
                    onTextChange={(targetSegment, text) => patchSegment(targetSegment, { text })}
                    onToggleExport={() => toggleExportSelection(segment.id)}
                    onSplit={() => {
                      setSelectedId(segment.id);
                      setSplitTarget(segment);
                    }}
                  />
                ))}
              </div>
            </section>
          ))}
          {filtered.length === 0 && (
            <p className="empty panel">
              {groupSegments.length === 0
                ? (libraryGroup === "finished" ? "暂无成片导入分析片段。" : "暂无用户导入的零散素材。")
                : "没有匹配搜索条件的片段。"}
            </p>
          )}
        </div>

        <aside className="panel segment-editor">
          {selected ? (
            <>
              <div className="segment-preview-sticky">
                <div className="section-title">
                  <div>
                    <h2>片段微调</h2>
                    <p>{selected.video_name}</p>
                  </div>
                  <button className="primary-action" onClick={saveSegment}>保存</button>
                </div>
                <div className={`large-preview-shell ${previewOrientation}`}>
                  <video
                    key={`${selected.id}-${previewVersion}`}
                    ref={previewRef}
                    src={`${API_BASE_URL}/segments/${selected.id}/preview?v=${previewVersion}`}
                    controls
                    tabIndex={0}
                    onClick={(event) => event.currentTarget.focus()}
                    onKeyDown={handleVideoShortcut}
                    onLoadedMetadata={handlePreviewLoaded}
                    onPlay={(event) => {
                      if (isPreviewAtEnd(event.currentTarget)) {
                        event.currentTarget.currentTime = 0;
                      }
                    }}
                    onTimeUpdate={handlePreviewTimeUpdate}
                  />
                </div>
              </div>
              <div className="clip-time-label">{formatClockPrecise(selected.start_seconds)} - {formatClockPrecise(selected.end_seconds)}</div>
              <div className="trim-inline-row">
                <label>
                  <span>入点</span>
                  <input type="number" step="0.1" value={draft.start_seconds ?? selected.start_seconds} onChange={(event) => setDraft((current) => ({ ...current, start_seconds: Number(event.target.value) }))} />
                </label>
                <div className="micro-controls">
                  <button onClick={() => nudgeSegment(selected, "start", -0.1)}>入-</button>
                  <button onClick={() => nudgeSegment(selected, "start", 0.1)}>入+</button>
                  <button onClick={() => nudgeSegment(selected, "end", -0.1)}>出-</button>
                  <button onClick={() => nudgeSegment(selected, "end", 0.1)}>出+</button>
                </div>
                <label>
                  <input type="number" step="0.1" value={draft.end_seconds ?? selected.end_seconds} onChange={(event) => setDraft((current) => ({ ...current, end_seconds: Number(event.target.value) }))} />
                  <span>出点</span>
                </label>
              </div>
              <div className="tag-line editor-tag-pills">
                <CardTagPicker
                  label="语义"
                  options={SEGMENT_TYPES}
                  values={splitMultiValue(draft.semantic_type ?? selected.semantic_type)}
                  onChange={(values) => setDraft((current) => ({ ...current, semantic_type: joinMultiValue(values) }))}
                />
                <CardTagPicker
                  label="位置"
                  options={POSITION_TYPES}
                  values={splitMultiValue(draft.position_type ?? selected.position_type)}
                  onChange={(values) => setDraft((current) => ({ ...current, position_type: joinMultiValue(values) }))}
                />
                <CardFreeTagPicker
                  label="卖点"
                  values={splitMultiValue(draft.selling_points ?? selected.selling_points)}
                  onChange={(values) => setDraft((current) => ({ ...current, selling_points: joinMultiValue(values) }))}
                />
                <CardFreeTagPicker
                  label="画面"
                  values={splitMultiValue(draft.visual_tags ?? selected.visual_tags)}
                  onChange={(values) => setDraft((current) => ({ ...current, visual_tags: joinMultiValue(values) }))}
                />
              </div>
            </>
          ) : (
            <p className="empty">选择左侧片段后微调。</p>
          )}
        </aside>
      </section>
      {splitTarget && (
        <SegmentSplitDialog
          segment={splitTarget}
          transcriptSegments={parseTranscriptSegments(props.videos.find((video) => video.id === splitTarget.video_id)?.transcript_segments)}
          onClose={() => setSplitTarget(null)}
          onConfirm={(cutPoints) => splitSegment(splitTarget, cutPoints)}
        />
      )}
    </>
  );
}

function MultiValueEditor(props: { label: string; options: string[]; values: string[]; onChange: (values: string[]) => void }) {
  function toggle(value: string) {
    if (props.values.includes(value)) {
      props.onChange(props.values.filter((item) => item !== value));
      return;
    }
    props.onChange([...props.values, value]);
  }

  return (
    <details className="inline-multi-select">
      <summary>
        <span>{props.label}</span>
        <strong title={props.values.join(" / ")}>{formatCompactTags(props.values, "未选择")}</strong>
      </summary>
      <div className="inline-multi-menu">
        {props.options.map((option) => (
          <label key={option}>
            <input checked={props.values.includes(option)} onChange={() => toggle(option)} type="checkbox" />
            {option}
          </label>
        ))}
      </div>
    </details>
  );
}

function formatCompactTags(values: string[], emptyLabel: string) {
  if (values.length === 0) return emptyLabel;
  const visible = values.slice(0, 2).join(" / ");
  return values.length > 2 ? `${visible} / ...` : visible;
}

function CompactTagChips(props: { values: string[]; limit?: number }) {
  const limit = props.limit ?? 2;
  const visible = props.values.slice(0, limit);
  const hidden = props.values.slice(limit);
  return (
    <>
      {visible.map((tag) => <TagChip key={tag} tag={tag} />)}
      {hidden.length > 0 && (
        <span className="tag-chip tag-color-default tag-overflow-chip" data-overflow={hidden.join(" / ")} title={hidden.join(" / ")}>
          ...
        </span>
      )}
    </>
  );
}

function SegmentCard(props: {
  segment: Segment;
  active: boolean;
  index: number;
  viewMode: "grid" | "list";
  selectedForExport: boolean;
  onSelect: () => void;
  onNudge: (segment: Segment, boundary: "start" | "end", delta: number) => void;
  onTagsChange: (segment: Segment, field: "semantic_type" | "position_type" | "selling_points" | "visual_tags", values: string[]) => void;
  onTextChange: (segment: Segment, text: string) => void;
  onToggleExport: () => void;
  onSplit: () => void;
}) {
  const duration = Math.max(0, props.segment.end_seconds - props.segment.start_seconds);
  return (
    <article
      className={props.active ? "segment-card active" : "segment-card"}
      onClick={props.onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          props.onSelect();
        }
      }}
      role="button"
      tabIndex={0}
    >
      <label className="segment-export-check" onClick={(event) => event.stopPropagation()}>
        <input checked={props.selectedForExport} onChange={props.onToggleExport} type="checkbox" />
      </label>
      <div className="segment-thumb-wrap">
        <img src={`${API_BASE_URL}/segments/${props.segment.id}/thumbnail`} />
        <span>#{props.index}</span>
        <strong>{duration.toFixed(1)}s</strong>
      </div>
      <div>
        <div className="segment-type-line"><CompactTagChips values={splitMultiValue(props.segment.semantic_type)} /></div>
        <small>{formatClock(props.segment.start_seconds)} · 台词 {props.segment.text.length}字</small>
        <textarea
          className="segment-card-textarea"
          defaultValue={props.segment.text}
          onBlur={(event) => {
            const nextText = event.currentTarget.value.trim();
            if (nextText !== props.segment.text) {
              props.onTextChange(props.segment, nextText);
            }
          }}
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
          placeholder="无转录文本"
          rows={4}
        />
        {(props.segment.selling_points || props.segment.visual_tags) && (
          <small>
            {[...splitMultiValue(props.segment.selling_points), ...splitMultiValue(props.segment.visual_tags)].slice(0, 5).join(" / ")}
          </small>
        )}
        {props.viewMode === "list" && <small>{props.segment.video_name}</small>}
      </div>
      <div className="tag-line">
        <CardTagPicker
          label="内容"
          options={SEGMENT_TYPES}
          values={splitMultiValue(props.segment.semantic_type)}
          onChange={(values) => props.onTagsChange(props.segment, "semantic_type", values)}
        />
        <CardTagPicker
          label="位置"
          options={POSITION_TYPES}
          values={splitMultiValue(props.segment.position_type)}
          onChange={(values) => props.onTagsChange(props.segment, "position_type", values)}
        />
        <CardFreeTagPicker
          label="卖点"
          values={splitMultiValue(props.segment.selling_points)}
          onChange={(values) => props.onTagsChange(props.segment, "selling_points", values)}
        />
        <CardFreeTagPicker
          label="画面"
          values={splitMultiValue(props.segment.visual_tags)}
          onChange={(values) => props.onTagsChange(props.segment, "visual_tags", values)}
        />
      </div>
      <div className="card-micro-controls">
        <button title="起点提前 0.1 秒" onClick={(event) => { event.stopPropagation(); props.onNudge(props.segment, "start", -0.1); }}>入-</button>
        <button title="起点延后 0.1 秒" onClick={(event) => { event.stopPropagation(); props.onNudge(props.segment, "start", 0.1); }}>入+</button>
        <button title="终点提前 0.1 秒" onClick={(event) => { event.stopPropagation(); props.onNudge(props.segment, "end", -0.1); }}>出-</button>
        <button title="终点延后 0.1 秒" onClick={(event) => { event.stopPropagation(); props.onNudge(props.segment, "end", 0.1); }}>出+</button>
        <button title="拆成多个小分镜" onClick={(event) => { event.stopPropagation(); props.onSplit(); }}>拆分</button>
      </div>
    </article>
  );
}

function SegmentSplitDialog(props: {
  segment: Segment;
  transcriptSegments: TranscriptSegment[];
  onClose: () => void;
  onConfirm: (cutPoints: number[]) => void;
}) {
  const [cutPoints, setCutPoints] = useState<number[]>([]);
  const [previewTime, setPreviewTime] = useState(0);
  const [previewRangeIndex, setPreviewRangeIndex] = useState<number | null>(null);
  const [splitPlaybackMode, setSplitPlaybackMode] = useState<"single" | "sequence" | null>(null);
  const [previewSource, setPreviewSource] = useState("");
  const [splitError, setSplitError] = useState("");
  const [previewNonce, setPreviewNonce] = useState(0);
  const suppressInitialSplitAutoplayRef = useRef(true);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const splitPreviewStartingRef = useRef(false);
  useVideoKeyboardShortcuts(videoRef);
  const segmentDuration = Math.max(0, props.segment.end_seconds - props.segment.start_seconds);
  const scriptItems = props.transcriptSegments.filter((item) => {
    const overlap = Math.min(props.segment.end_seconds, item.end_seconds) - Math.max(props.segment.start_seconds, item.start_seconds);
    return overlap > 0;
  });
  const scriptCuts = scriptItems
    .map((item) => item.end_seconds)
    .filter((point) => point > props.segment.start_seconds + 0.3 && point < props.segment.end_seconds - 0.3);
  const ranges = [props.segment.start_seconds, ...cutPoints, props.segment.end_seconds].map((start, index, bounds) => ({
    start,
    end: bounds[index + 1],
  })).filter((item) => Number.isFinite(item.end));
  const fullPreviewSource = `${API_BASE_URL}/segments/${props.segment.id}/preview`;
  const activePreviewSource = previewSource || fullPreviewSource;

  function rangePreviewSource(range: { start: number; end: number }) {
    return `${API_BASE_URL}/segments/${props.segment.id}/range-preview?start_seconds=${range.start.toFixed(3)}&end_seconds=${range.end.toFixed(3)}`;
  }

  function addCutPoint(value: number) {
    const point = Number(value.toFixed(3));
    if (point <= props.segment.start_seconds || point >= props.segment.end_seconds) {
      setSplitError("切点必须在当前分镜范围内。");
      return false;
    }
    if (point <= props.segment.start_seconds + 0.3 || point >= props.segment.end_seconds - 0.3) {
      setSplitError("切点离分镜头尾太近，拆出来的小分镜至少要 0.3 秒。");
      return false;
    }
    if (cutPoints.some((item) => Math.abs(item - point) < 0.05)) {
      setSplitError("这个位置已经有切点了。");
      return false;
    }
    setSplitError("");
    setCutPoints((current) => Array.from(new Set([...current, point])).sort((a, b) => a - b));
    return true;
  }

  function removeCutPoint(point: number) {
    setCutPoints((current) => current.filter((item) => item !== point));
  }

  function seekToCut(point: number) {
    const video = videoRef.current;
    setPreviewRangeIndex(null);
    setSplitPlaybackMode(null);
    setPreviewSource(fullPreviewSource);
    if (!video) return;
    video.currentTime = Math.max(0, Math.min(segmentDuration, point - props.segment.start_seconds));
    video.pause();
  }

  function addCurrentPreviewTime() {
    const video = videoRef.current;
    if (!video) return;
    addCutPoint((previewRangeIndex === null ? props.segment.start_seconds : ranges[previewRangeIndex].start) + video.currentTime);
  }

  function seekRelativeTime(value: number) {
    const video = videoRef.current;
    if (!video) return;
    setPreviewRangeIndex(null);
    setSplitPlaybackMode(null);
    setPreviewSource(fullPreviewSource);
    video.currentTime = Math.max(0, Math.min(segmentDuration, value));
  }

  function previewRange(index: number, playbackMode: "single" | "sequence" = "single") {
    const range = ranges[index];
    const video = videoRef.current;
    if (!range || !video) return;
    setPreviewRangeIndex(index);
    setSplitPlaybackMode(playbackMode);
    setPreviewSource(rangePreviewSource(range));
    setPreviewNonce((current) => current + 1);
    splitPreviewStartingRef.current = true;
    window.setTimeout(() => {
      splitPreviewStartingRef.current = false;
    }, 80);
  }

  function previewAllRanges() {
    if (ranges.length === 0) return;
    previewRange(0, "sequence");
  }

  function handleSplitPreviewPlay(video: HTMLVideoElement) {
    if (splitPreviewStartingRef.current) return;
    if (cutPoints.length === 0 || previewRangeIndex !== null) return;
    video.pause();
    previewAllRanges();
  }

  function handleSplitPreviewTimeUpdate(video: HTMLVideoElement) {
    const currentRange = previewRangeIndex === null ? null : ranges[previewRangeIndex];
    setPreviewTime(Number(video.currentTime.toFixed(1)));
    if (previewRangeIndex === null) return;
    if (!currentRange || video.currentTime < currentRange.end - currentRange.start - 0.04) return;
    if (splitPlaybackMode !== "sequence") {
      video.pause();
      video.currentTime = Math.max(0, currentRange.end - props.segment.start_seconds);
      setSplitPlaybackMode(null);
      return;
    }
    const nextIndex = previewRangeIndex + 1;
    if (nextIndex < ranges.length) {
      previewRange(nextIndex, "sequence");
      return;
    }
    video.pause();
    setPreviewRangeIndex(null);
    setSplitPlaybackMode(null);
  }

  return (
    <div className="modal-backdrop" onClick={props.onClose}>
      <section className="split-dialog" onClick={(event) => event.stopPropagation()}>
        <div className="split-head">
          <div>
            <h2>拆分分镜</h2>
            <p>{props.segment.video_name} · {formatClockPrecise(props.segment.start_seconds)} - {formatClockPrecise(props.segment.end_seconds)}</p>
          </div>
        </div>
        <div className="split-body">
          <div className="split-preview">
            <video
              key={`${activePreviewSource}-${previewNonce}`}
              ref={videoRef}
              src={activePreviewSource}
              controls
              tabIndex={0}
              onClick={(event) => event.currentTarget.focus()}
              onKeyDown={handleVideoShortcut}
              onLoadedMetadata={(event) => {
                event.currentTarget.currentTime = 0;
                setPreviewTime(0);
                if (suppressInitialSplitAutoplayRef.current) {
                  event.currentTarget.pause();
                  suppressInitialSplitAutoplayRef.current = false;
                  return;
                }
                if (previewRangeIndex !== null) {
                  splitPreviewStartingRef.current = true;
                  void event.currentTarget.play().catch(() => undefined);
                  window.setTimeout(() => {
                    splitPreviewStartingRef.current = false;
                  }, 80);
                }
              }}
              onEnded={() => {
                if (previewRangeIndex === null || splitPlaybackMode !== "sequence") return;
                const nextIndex = previewRangeIndex + 1;
                if (nextIndex < ranges.length) {
                  previewRange(nextIndex, "sequence");
                  return;
                }
                setPreviewRangeIndex(null);
                setSplitPlaybackMode(null);
              }}
              onPlay={(event) => handleSplitPreviewPlay(event.currentTarget)}
              onTimeUpdate={(event) => handleSplitPreviewTimeUpdate(event.currentTarget)}
            />
            <input
              className="split-scrubber"
              max={previewRangeIndex === null ? segmentDuration : Math.max(0, ranges[previewRangeIndex].end - ranges[previewRangeIndex].start)}
              min={0}
              onChange={(event) => seekRelativeTime(Number(event.target.value))}
              step={0.1}
              type="range"
              value={Math.min(previewRangeIndex === null ? segmentDuration : Math.max(0, ranges[previewRangeIndex].end - ranges[previewRangeIndex].start), previewTime)}
            />
            <div className="split-primary-actions">
              <button className="primary-action" onClick={addCurrentPreviewTime}>添加当前时间为切点</button>
              <button className="secondary" disabled={cutPoints.length === 0} onClick={previewAllRanges}>预览裁切结果</button>
            </div>
            <div className="split-preview-meta">
              <span>当前画面 {formatClockPrecise((previewRangeIndex === null ? props.segment.start_seconds : ranges[previewRangeIndex].start) + previewTime)}</span>
              <span>相对 {formatClockPrecise(previewTime)} / {formatClockPrecise(previewRangeIndex === null ? segmentDuration : Math.max(0, ranges[previewRangeIndex].end - ranges[previewRangeIndex].start))}</span>
            </div>
          </div>
          <div className="split-tools">
            <div className="split-tool-title">
              <strong>按台词裁切</strong>
              <span>也可以拖动左侧预览，再点“添加当前时间为切点”。</span>
            </div>
            <div className="script-cut-list">
              {scriptItems.length === 0 && <p className="empty">这个视频没有可用台词时间戳，可以拖动左侧预览后添加当前时间为切点。</p>}
              {scriptItems.map((item, index) => {
                const canCut = scriptCuts.includes(item.end_seconds);
                return (
                  <button
                    className={canCut ? "script-cut-row" : "script-cut-row disabled"}
                    disabled={!canCut}
                    key={`${item.start_seconds}-${index}`}
                    onClick={() => addCutPoint(item.end_seconds)}
                    type="button"
                  >
                    <div>
                      <small>{formatClockPrecise(item.start_seconds)} - {formatClockPrecise(item.end_seconds)}</small>
                      <p>{item.text}</p>
                    </div>
                    <strong>{canCut ? "切开" : "不可切"}</strong>
                  </button>
                );
              })}
            </div>
            {splitError && <p className="warning-hint">{splitError}</p>}
            <div className="cut-point-list">
              <div className="split-subhead">
                <strong>切点 {cutPoints.length}</strong>
                <button disabled={cutPoints.length === 0} onClick={() => setCutPoints([])}>清空</button>
              </div>
              {cutPoints.map((point) => (
                <button className="cut-point-pill" key={point} onClick={() => seekToCut(point)}>
                  {formatClockPrecise(point)} <span onClick={(event) => { event.stopPropagation(); removeCutPoint(point); }}>×</span>
                </button>
              ))}
            </div>
            <div className="split-ranges">
              <strong>将生成 {ranges.length} 个小分镜（点击预览）</strong>
              {ranges.map((range, index) => (
                <button
                  className={previewRangeIndex === index ? "split-range-card active" : "split-range-card"}
                  key={`${range.start}-${range.end}`}
                  onClick={() => previewRange(index)}
                  type="button"
                >
                  <span>#{index + 1}</span>
                  <strong>{formatClockPrecise(range.start)} - {formatClockPrecise(range.end)}</strong>
                  <small>{(range.end - range.start).toFixed(1)}s</small>
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="modal-actions">
          <button className="secondary" onClick={props.onClose}>取消</button>
          <button className="primary-action" disabled={cutPoints.length === 0} onClick={() => props.onConfirm(cutPoints)}>确认拆分</button>
        </div>
      </section>
    </div>
  );
}

function CardTagPicker(props: { label: string; options: string[]; values: string[]; onChange: (values: string[]) => void }) {
  function toggle(value: string) {
    if (props.values.includes(value)) {
      props.onChange(props.values.filter((item) => item !== value));
      return;
    }
    props.onChange([...props.values, value]);
  }

  return (
    <details
      className="card-tag-picker"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      <summary>
        <span>{props.label}</span>
        <strong title={props.values.join(" / ")}>{formatCompactTags(props.values, "未选择")}</strong>
      </summary>
      <div className="card-tag-menu">
        {props.options.map((option) => (
          <label key={option}>
            <input checked={props.values.includes(option)} onChange={() => toggle(option)} type="checkbox" />
            {option}
          </label>
        ))}
      </div>
    </details>
  );
}

function CardFreeTagPicker(props: { label: string; values: string[]; onChange: (values: string[]) => void }) {
  const [draft, setDraft] = useState(props.values.join(","));
  useEffect(() => setDraft(props.values.join(",")), [props.values.join(",")]);

  function save() {
    props.onChange(splitMultiValue(draft));
  }

  return (
    <details
      className="card-tag-picker"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      <summary>
        <span>{props.label}</span>
        <strong title={props.values.join(" / ")}>{formatCompactTags(props.values, "未填写")}</strong>
      </summary>
      <div className="card-tag-menu">
        <label>
          <span>{props.label} tag</span>
          <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="逗号分隔" />
        </label>
        <button className="secondary" onClick={save}>保存</button>
      </div>
    </details>
  );
}

function SchemeWorkspace(props: {
  project: Project;
  segments: Segment[];
  schemes: Scheme[];
  selectedScheme: Scheme | null;
  setSelectedScheme: (scheme: Scheme | null) => void;
  onRefresh: () => void;
  setMessage: (value: string) => void;
  setError: (value: string) => void;
}) {
  const [strategyCount, setStrategyCount] = useState(5);
  const [outputsPerStrategy, setOutputsPerStrategy] = useState(2);
  const [targetDuration, setTargetDuration] = useState(30);
  const [durationMin, setDurationMin] = useState(20);
  const [durationMax, setDurationMax] = useState(40);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedTimelineId, setSelectedTimelineId] = useState<number | null>(null);
  const [replacementForId, setReplacementForId] = useState<number | null>(null);
  const [expandedStrategyIds, setExpandedStrategyIds] = useState<string[]>([]);
  const [schemeExportDir, setSchemeExportDir] = useState("");
  const [timelinePreviewVersion, setTimelinePreviewVersion] = useState(0);
  const [timelinePreviewMode, setTimelinePreviewMode] = useState<"start" | "end" | null>(null);
  const [timelinePreviewSource, setTimelinePreviewSource] = useState<"scheme" | "segment">("scheme");
  const timelinePreviewRef = useRef<HTMLVideoElement | null>(null);
  const pendingPreviewPlayRef = useRef<{ offset: number; play: boolean } | null>(null);
  useVideoKeyboardShortcuts(timelinePreviewRef);
  const videoCount = new Set(props.segments.map((segment) => segment.video_id)).size;
  const recommendedStrategies = props.segments.length < 20 ? 3 : props.segments.length < 60 ? 4 : 5;
  const recommendedOutputs = videoCount <= 1 || props.segments.length < 20 ? 1 : 2;
  const recommendedSchemeCount = Math.min(30, recommendedStrategies * recommendedOutputs);
  const recommendedShotCount = Math.max(3, Math.min(12, Math.ceil((props.segments.length || 3) / Math.max(1, recommendedSchemeCount))));
  const totalSchemeCount = Math.min(30, strategyCount * outputsPerStrategy);
  const normalizedDurationMin = Math.min(durationMin, durationMax);
  const normalizedDurationMax = Math.max(durationMin, durationMax);
  const selectedSegments = props.selectedScheme?.segments ?? [];
  const selectedTimeline = selectedSegments.find((item) => item.scheme_segment_id === selectedTimelineId) ?? selectedSegments[0] ?? null;
  const schemeGroups = useMemo(() => {
    const groups = new Map<string, { id: string; title: string; description: string; schemes: Scheme[]; bestScore: number; repeatRate: number; duration: number }>();
    const strategyCounts = props.schemes.reduce<Record<string, number>>((counts, scheme) => {
      if (scheme.strategy_id) {
        const key = String(scheme.strategy_id);
        counts[key] = (counts[key] ?? 0) + 1;
      }
      return counts;
    }, {});
    const normalizedGroupName = (name: string) => name
      .replace(/[\s_-]*变体[A-Za-z0-9一二三四五六七八九十]+$/u, "")
      .replace(/[\s_-]*成片[A-Za-z0-9一二三四五六七八九十]+$/u, "")
      .trim();
    props.schemes.forEach((scheme, index) => {
      const strategyKey = scheme.strategy_id ? String(scheme.strategy_id) : "";
      const baseName = normalizedGroupName(scheme.name || scheme.scheme_description || "");
      const id = strategyKey && strategyCounts[strategyKey] > 1 ? `strategy-${strategyKey}` : `name-${baseName || index}`;
      const current = groups.get(id);
      const score = scheme.recommendation_score ?? 0;
      const repeatRate = scheme.repeat_rate ?? 0;
      const duration = scheme.actual_duration ?? scheme.estimated_duration;
      if (current) {
        current.schemes.push(scheme);
        current.bestScore = Math.max(current.bestScore, score);
        current.repeatRate = Math.min(current.repeatRate, repeatRate);
        current.duration = Math.max(current.duration, duration);
      } else {
        groups.set(id, {
          id,
          title: baseName || scheme.name || `方案组 ${groups.size + 1}`,
          description: scheme.scheme_description || scheme.differentiation || "",
          schemes: [scheme],
          bestScore: score,
          repeatRate,
          duration,
        });
      }
    });
    return Array.from(groups.values()).sort((a, b) => b.bestScore - a.bestScore);
  }, [props.schemes]);

  useEffect(() => {
    setStrategyCount(recommendedStrategies);
    setOutputsPerStrategy(recommendedOutputs);
  }, [props.project.id, recommendedStrategies, recommendedOutputs]);

  useEffect(() => {
    if (!selectedSegments.length) {
      setSelectedTimelineId(null);
      setReplacementForId(null);
      return;
    }
    if (!selectedTimelineId || !selectedSegments.some((item) => item.scheme_segment_id === selectedTimelineId)) {
      setSelectedTimelineId(selectedSegments[0].scheme_segment_id);
    }
  }, [props.selectedScheme?.id, selectedSegments.length, selectedTimelineId]);

  async function generate() {
    setBusy(true);
    try {
      const data = await api<Scheme[]>(`/projects/${props.project.id}/schemes/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_duration: targetDuration,
          duration_min: normalizedDurationMin,
          duration_max: normalizedDurationMax,
          strategy_count: strategyCount,
          outputs_per_strategy: outputsPerStrategy,
          scheme_count: totalSchemeCount,
          requirement_prompt: prompt,
        }),
      });
      props.setMessage(`已生成 ${data.length} 个方案。`);
      props.onRefresh();
      if (data[0]) {
        props.setSelectedScheme(data[0]);
        setExpandedStrategyIds(data[0].strategy_id ? [String(data[0].strategy_id)] : []);
        setSelectedTimelineId(data[0].segments?.[0]?.scheme_segment_id ?? null);
        playSchemePreviewAt(0);
      }
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "未知错误");
    } finally {
      setBusy(false);
    }
  }

  async function openScheme(schemeId: number) {
    const scheme = await api<Scheme>(`/schemes/${schemeId}`);
    props.setSelectedScheme(scheme);
    setSelectedTimelineId(scheme.segments?.[0]?.scheme_segment_id ?? null);
    setReplacementForId(null);
    playSchemePreviewAt(0);
  }

  function toggleStrategyGroup(groupId: string) {
    setExpandedStrategyIds((current) => (
      current.includes(groupId) ? current.filter((id) => id !== groupId) : [...current, groupId]
    ));
  }

  async function patchSchemeSegment(schemeSegmentId: number, body: object) {
    const scheme = await api<Scheme>(`/scheme-segments/${schemeSegmentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    props.setSelectedScheme(scheme);
    const action = (body as { action?: string }).action;
    const stillExists = scheme.segments?.some((item) => item.scheme_segment_id === schemeSegmentId);
    setSelectedTimelineId(action === "delete" || !stillExists ? scheme.segments?.[0]?.scheme_segment_id ?? null : schemeSegmentId);
    setReplacementForId(null);
    setTimelinePreviewMode(action === "delete" ? null : "start");
    setTimelinePreviewSource("scheme");
    setTimelinePreviewVersion((current) => current + 1);
    props.onRefresh();
  }

  async function nudgeTimelineSegment(segment: SchemeSegment, boundary: "start" | "end", delta: number) {
    const minDuration = 0.3;
    const nextStart = boundary === "start" ? Math.max(0, Number((segment.start_seconds + delta).toFixed(1))) : segment.start_seconds;
    const nextEnd = boundary === "end" ? Math.max(minDuration, Number((segment.end_seconds + delta).toFixed(1))) : segment.end_seconds;
    if (nextEnd - nextStart < minDuration) {
      props.setError("片段至少保留 0.3 秒。");
      return;
    }
    try {
      await api<Segment>(`/segments/${segment.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start_seconds: nextStart, end_seconds: nextEnd }),
      });
      if (props.selectedScheme) {
        props.setSelectedScheme(await api<Scheme>(`/schemes/${props.selectedScheme.id}`));
      }
      setSelectedTimelineId(segment.scheme_segment_id);
      setTimelinePreviewMode(boundary);
      setTimelinePreviewVersion((current) => current + 1);
      props.onRefresh();
      props.setMessage("片段边界已调整。");
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "片段调整失败");
    }
  }

  async function exportScheme() {
    if (!props.selectedScheme) return;
    try {
      let outputDir = schemeExportDir;
      if (!outputDir && window.electronAPI?.selectExportDirectory) {
        const selectedPath = await window.electronAPI.selectExportDirectory();
        if (!selectedPath) return;
        outputDir = selectedPath;
        setSchemeExportDir(selectedPath);
      }
      const result = await api<{ export_path: string }>(`/schemes/${props.selectedScheme.id}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ output_dir: outputDir || undefined }),
      });
      props.setMessage(`已导出：${result.export_path}`);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "未知错误");
    }
  }

  const usedIds = new Set(props.selectedScheme?.segments?.map((item) => item.id) ?? []);
  const actualDuration = selectedSegments.reduce((sum, item) => sum + Math.max(0, item.end_seconds - item.start_seconds), 0);
  const schemeTags = Array.from(new Set(selectedSegments.flatMap((item) => splitMultiValue(item.semantic_type))));
  const selectedTimelineOffset = selectedTimeline ? schemePreviewOffsetFor(selectedTimeline) : 0;
  const activePreviewOffset = timelinePreviewSource === "scheme" ? selectedTimelineOffset : 0;

  function schemePreviewOffsetFor(target: SchemeSegment) {
    let offset = 0;
    for (const item of selectedSegments) {
      if (item.scheme_segment_id === target.scheme_segment_id) {
        return offset;
      }
      offset += previewClipDuration(item);
    }
    return 0;
  }

  function previewClipDuration(item: SchemeSegment) {
    const rawDuration = Math.max(0, item.end_seconds - item.start_seconds);
    const trimmedDuration = rawDuration - SCHEME_PREVIEW_START_GUARD_SECONDS - SCHEME_PREVIEW_END_GUARD_SECONDS;
    return trimmedDuration > 0 ? trimmedDuration : rawDuration;
  }

  function playSchemePreviewAt(offset: number) {
    pendingPreviewPlayRef.current = { offset, play: true };
    setTimelinePreviewSource("scheme");
    setTimelinePreviewMode(null);
    setTimelinePreviewVersion((current) => current + 1);
  }

  function isTimelinePreviewAtEnd(video: HTMLVideoElement) {
    return video.duration > 0 && video.currentTime >= video.duration - 0.12;
  }

  function playTimelinePreviewFromStartIfEnded() {
    const video = timelinePreviewRef.current;
    if (!video) return;
    if (isTimelinePreviewAtEnd(video)) {
      video.currentTime = selectedTimeline ? activePreviewOffset : 0;
    }
    void video.play().catch(() => undefined);
  }

  function pauseTimelinePreview() {
    timelinePreviewRef.current?.pause();
  }

  function handleTimelinePreviewLoaded() {
    const video = timelinePreviewRef.current;
    if (!video) return;
    if (pendingPreviewPlayRef.current) {
      const pending = pendingPreviewPlayRef.current;
      pendingPreviewPlayRef.current = null;
      video.currentTime = Math.max(0, pending.offset);
      if (pending.play) {
        void video.play().catch(() => undefined);
      } else {
        video.pause();
      }
      return;
    }
    if (!timelinePreviewMode) {
      video.currentTime = selectedTimeline ? activePreviewOffset : 0;
      video.pause();
      return;
    }
    if (timelinePreviewMode === "end") {
      const segmentDuration = selectedTimeline && timelinePreviewSource === "scheme" ? previewClipDuration(selectedTimeline) : video.duration;
      video.currentTime = Math.max(0, activePreviewOffset + segmentDuration - 0.8);
    } else {
      video.currentTime = activePreviewOffset;
    }
    void video.play().catch(() => undefined);
  }

  function handleTimelinePreviewTimeUpdate() {
    const video = timelinePreviewRef.current;
    if (!video || !timelinePreviewMode) return;
    const segmentDuration = selectedTimeline && timelinePreviewSource === "scheme" ? previewClipDuration(selectedTimeline) : video.duration;
    const stopAt = timelinePreviewMode === "end"
      ? Math.min(video.duration, activePreviewOffset + segmentDuration - 0.05)
      : Math.min(video.duration, activePreviewOffset + 0.8);
    if (video.currentTime >= stopAt) {
      video.pause();
      video.currentTime = stopAt;
      setTimelinePreviewMode(null);
    }
  }

  function getReplacementCandidates(item: SchemeSegment) {
    return props.segments
      .filter((segment) => {
        if (usedIds.has(segment.id)) return false;
        return multiValuesOverlap(segment.semantic_type, item.semantic_type) && multiValuesOverlap(segment.position_type, item.position_type);
      })
      .sort((left, right) => {
        const leftSameSource = left.video_id === item.video_id ? 1 : 0;
        const rightSameSource = right.video_id === item.video_id ? 1 : 0;
        return leftSameSource - rightSameSource;
      });
  }
  return (
    <section className="scheme-layout">
      <div className="scheme-master">
        <section className="panel generation-panel">
          <div className="section-title">
            <div>
              <h2>混剪方案</h2>
              <p>{props.schemes.length} 成片 · {props.segments.length} 分镜 · {videoCount} 视频</p>
            </div>
          </div>
          <label>混剪需求</label>
          <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={3} placeholder="例如：控制在30秒左右，节奏快一点，结尾强促单，突出产品方案和行动号召" />
          <div className="generation-controls">
            <label>策略数量 <input type="number" min={1} max={15} value={strategyCount} onChange={(event) => setStrategyCount(Number(event.target.value))} /></label>
            <label>目标秒数 <input type="number" min={5} max={180} value={targetDuration} onChange={(event) => setTargetDuration(Number(event.target.value))} /></label>
            <button className="primary-action" disabled={busy || props.segments.length === 0} onClick={generate}>{busy ? "生成中..." : "生成方案"}</button>
          </div>
          <div className="generation-controls duration-controls">
            <label>最短秒数 <input type="number" min={5} max={180} value={durationMin} onChange={(event) => setDurationMin(Number(event.target.value))} /></label>
            <label>最长秒数 <input type="number" min={5} max={180} value={durationMax} onChange={(event) => setDurationMax(Number(event.target.value))} /></label>
            <span>实际请求：{normalizedDurationMin}-{normalizedDurationMax}s，贴近 {targetDuration}s</span>
          </div>
          <label className="range-field">
            <span>每个策略成片数 <strong>{outputsPerStrategy}</strong></span>
            <input type="range" min={1} max={5} value={outputsPerStrategy} onChange={(event) => setOutputsPerStrategy(Number(event.target.value))} />
          </label>
          <div className="recommendation-strip">
            <span>推荐策略 {recommendedStrategies}</span>
            <span>推荐成片 {recommendedSchemeCount}</span>
            <span>推荐分镜 {recommendedShotCount}</span>
            <strong>本次将生成 {totalSchemeCount} 条成片</strong>
          </div>
          <p className="field-hint">需要控制时长时请写在混剪需求里，系统不会再强行删减或补齐分镜；方案列表会按素材重复率自动推荐排序。</p>
        </section>
        <section className="scheme-list">
          {schemeGroups.map((group, groupIndex) => {
            const expanded = expandedStrategyIds.includes(group.id) || group.schemes.some((scheme) => scheme.id === props.selectedScheme?.id);
            const bestScheme = group.schemes[0];
            return (
              <section className="scheme-group" key={group.id}>
                <button className={expanded ? "scheme-group-head active" : "scheme-group-head"} onClick={() => toggleStrategyGroup(group.id)}>
                  <span className="scheme-index">#{groupIndex + 1}</span>
                  <strong>{group.title}</strong>
                  <span>{group.schemes.length} 条成片 · 最低重复率 {Math.round(group.repeatRate * 100)}%</span>
                  <small>{bestScheme?.is_recommended ? "推荐 · " : ""}{bestScheme?.style || "未标注风格"} · 最长 {group.duration.toFixed(0)}s</small>
                </button>
                {expanded && (
                  <div className="scheme-variant-list">
                    {group.schemes.map((scheme, index) => (
                      <button className={props.selectedScheme?.id === scheme.id ? "scheme-card active" : "scheme-card"} key={scheme.id} onClick={() => openScheme(scheme.id)}>
                        <span className="scheme-index">{index + 1}</span>
                        <strong>{scheme.scheme_description || scheme.name}</strong>
                        <span>{scheme.segment_count ?? scheme.segments?.length ?? 0} 分镜 · {(scheme.actual_duration ?? scheme.estimated_duration).toFixed(0)}s</span>
                        <small>{scheme.is_recommended ? "推荐 · " : ""}重复率 {Math.round((scheme.repeat_rate ?? 0) * 100)}% · {scheme.target_audience || "通用受众"}</small>
                      </button>
                    ))}
                  </div>
                )}
              </section>
            );
          })}
          {props.schemes.length === 0 && <p className="empty panel">暂无方案。先生成多个策略，再选择一个进入详情。</p>}
        </section>
      </div>

      <aside className="panel scheme-detail">
        {props.selectedScheme ? (
          <>
            <div className="section-title">
              <div>
                <h2>{props.selectedScheme.name}</h2>
                <p>{props.selectedScheme.scheme_description}</p>
              </div>
              <div className="scheme-export-actions">
                <button className="secondary" onClick={async () => {
                  if (!window.electronAPI?.selectExportDirectory) {
                    props.setError("当前窗口没有连接到系统文件夹选择器，请重启软件后再试。");
                    return;
                  }
                  const selectedPath = await window.electronAPI.selectExportDirectory();
                  if (selectedPath) setSchemeExportDir(selectedPath);
                }}>保存位置</button>
                <button className="primary-action" onClick={exportScheme}>导出方案</button>
              </div>
            </div>
            {schemeExportDir && <p className="field-hint">保存到：{schemeExportDir}</p>}
            <div className="scheme-summary-grid">
              <div><span>时长</span><strong>{actualDuration.toFixed(1)}s</strong></div>
              <div><span>风格</span><strong>{props.selectedScheme.style || "未标注"}</strong></div>
              <div><span>受众</span><strong>{props.selectedScheme.target_audience || "通用受众"}</strong></div>
              <div><span>分镜</span><strong>{selectedSegments.length}</strong></div>
            </div>
            <section className="scheme-story">
              <h3>叙事结构</h3>
              <p>{props.selectedScheme.narrative_structure || "未生成叙事结构"}</p>
              <div className="tag-line">
                {schemeTags.map((tag) => <TagChip key={tag} tag={tag} />)}
              </div>
            </section>
            <section className="scheme-story">
              <h3>策略说明</h3>
              <p>{props.selectedScheme.strategy_reasoning || props.selectedScheme.differentiation || "未生成策略说明"}</p>
            </section>
            {selectedTimeline && (
              <section className="scheme-preview-editor">
                <div className="large-preview-shell scheme-preview-shell">
                  <video
                    key={`${props.selectedScheme.id}-${timelinePreviewVersion}`}
                    ref={timelinePreviewRef}
                    src={timelinePreviewSource === "scheme" ? `${API_BASE_URL}/schemes/${props.selectedScheme.id}/preview?v=${timelinePreviewVersion}` : `${API_BASE_URL}/segments/${selectedTimeline.id}/preview?v=${timelinePreviewVersion}`}
                  controls
                    tabIndex={0}
                    onClick={(event) => event.currentTarget.focus()}
                    onKeyDown={handleVideoShortcut}
                    onLoadedMetadata={handleTimelinePreviewLoaded}
                    onMouseEnter={playTimelinePreviewFromStartIfEnded}
                    onMouseLeave={pauseTimelinePreview}
                    onPlay={(event) => {
                      if (isTimelinePreviewAtEnd(event.currentTarget)) {
                        event.currentTarget.currentTime = activePreviewOffset;
                      }
                    }}
                    onTimeUpdate={handleTimelinePreviewTimeUpdate}
                  />
                </div>
                <div className="timeline-edit-head">
                  <div>
                    <strong>#{selectedSegments.findIndex((item) => item.scheme_segment_id === selectedTimeline.scheme_segment_id) + 1} <span className="inline-chip-list">{splitMultiValue(selectedTimeline.semantic_type).map((tag) => <TagChip key={tag} tag={tag} />)}</span></strong>
                    <span>{timelinePreviewSource === "scheme" ? "完整成片预览" : "单分镜预览"} · {formatClockPrecise(selectedTimeline.start_seconds)} - {formatClockPrecise(selectedTimeline.end_seconds)} · {selectedTimeline.video_name}</span>
                  </div>
                </div>
                <div className="micro-controls">
                  <button onClick={() => { setTimelinePreviewSource("scheme"); setTimelinePreviewMode("start"); setTimelinePreviewVersion((current) => current + 1); }}>看成片</button>
                  <button onClick={() => { setTimelinePreviewSource("segment"); setTimelinePreviewMode("start"); setTimelinePreviewVersion((current) => current + 1); }}>看分镜</button>
                  <button onClick={() => nudgeTimelineSegment(selectedTimeline, "start", -0.1)}>入-</button>
                  <button onClick={() => nudgeTimelineSegment(selectedTimeline, "start", 0.1)}>入+</button>
                  <button onClick={() => nudgeTimelineSegment(selectedTimeline, "end", -0.1)}>出-</button>
                  <button onClick={() => nudgeTimelineSegment(selectedTimeline, "end", 0.1)}>出+</button>
                </div>
              </section>
            )}
            <h3 className="timeline-title">分镜序列</h3>
            <div className="timeline">
              {selectedSegments.map((item, index) => {
                const candidates = getReplacementCandidates(item);
                return (
                  <article
                    className={selectedTimeline?.scheme_segment_id === item.scheme_segment_id ? "timeline-item active" : "timeline-item"}
                    key={item.scheme_segment_id}
                    onClick={() => {
                      setSelectedTimelineId(item.scheme_segment_id);
                      playSchemePreviewAt(schemePreviewOffsetFor(item));
                    }}
                  >
                    <div className="timeline-thumb">
                      <img src={`${API_BASE_URL}/segments/${item.id}/thumbnail`} />
                      <span>#{index + 1}</span>
                      <strong>{(item.end_seconds - item.start_seconds).toFixed(1)}s</strong>
                    </div>
                    <div>
                      <div className="timeline-head">
                        <strong className="inline-chip-list">{splitMultiValue(item.semantic_type).map((tag) => <TagChip key={tag} tag={tag} />)}</strong>
                        <small>{item.video_name} · {formatClockPrecise(item.start_seconds)} - {formatClockPrecise(item.end_seconds)}</small>
                      </div>
                      <p>{item.text}</p>
                      <small>{item.reasoning || item.position_reasoning}</small>
                      <div className="card-micro-controls">
                        <button onClick={(event) => { event.stopPropagation(); void nudgeTimelineSegment(item, "start", -0.1); }}>入-</button>
                        <button onClick={(event) => { event.stopPropagation(); void nudgeTimelineSegment(item, "start", 0.1); }}>入+</button>
                        <button onClick={(event) => { event.stopPropagation(); void nudgeTimelineSegment(item, "end", -0.1); }}>出-</button>
                        <button onClick={(event) => { event.stopPropagation(); void nudgeTimelineSegment(item, "end", 0.1); }}>出+</button>
                      </div>
                      <div className="action-row">
                        <button className="secondary" onClick={(event) => { event.stopPropagation(); void patchSchemeSegment(item.scheme_segment_id, { action: "move_up" }); }}>上移</button>
                        <button className="secondary" onClick={(event) => { event.stopPropagation(); void patchSchemeSegment(item.scheme_segment_id, { action: "move_down" }); }}>下移</button>
                        <button className="secondary" onClick={(event) => {
                          event.stopPropagation();
                          setSelectedTimelineId(item.scheme_segment_id);
                          setReplacementForId(replacementForId === item.scheme_segment_id ? null : item.scheme_segment_id);
                        }}>替换素材</button>
                        <button className="secondary" onClick={(event) => { event.stopPropagation(); void patchSchemeSegment(item.scheme_segment_id, { action: "delete" }); }}>删除</button>
                      </div>
                      {replacementForId === item.scheme_segment_id && (
                        <section className="replacement-panel inline-replacement" onClick={(event) => event.stopPropagation()}>
                          <div className="section-title">
                            <div>
                              <h3>替换素材</h3>
                              <p>同 tag 与同位置的可用片段</p>
                            </div>
                            <button className="secondary" onClick={() => setReplacementForId(null)}>收起</button>
                          </div>
                          <div className="replacement-list">
                            {candidates.map((segment) => (
                              <button
                                className="replacement-card"
                                key={segment.id}
                                onClick={() => patchSchemeSegment(item.scheme_segment_id, { segment_id: segment.id })}
                              >
                                <img src={`${API_BASE_URL}/segments/${segment.id}/thumbnail`} />
                                <span>{splitMultiValue(segment.semantic_type).join(" / ")} · {splitMultiValue(segment.position_type).join(" / ")}</span>
                                <strong>{segment.text.slice(0, 44) || `片段 #${segment.id}`}</strong>
                              </button>
                            ))}
                            {candidates.length === 0 && <p className="empty">没有同 tag 与同位置的可替换片段。</p>}
                          </div>
                        </section>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          </>
        ) : (
          <p className="empty">选择一个方案查看详情。</p>
        )}
      </aside>
    </section>
  );
}

function SettingsView(props: { settings: Settings; onSaved: () => void; setMessage: (value: string) => void; setError: (value: string) => void }) {
  const [draft, setDraft] = useState<Settings>(props.settings);
  useEffect(() => setDraft(props.settings), [props.settings]);

  function setValue(key: string, value: string) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  async function save() {
    try {
      await api("/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values: draft }),
      });
      props.setMessage("设置已保存。");
      props.onSaved();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "未知错误");
    }
  }

  async function test(target: "ai" | "asr" | "tts") {
    try {
      const result = await api<{ message: string }>("/settings/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target }),
      });
      props.setMessage(result.message);
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "未知错误");
    }
  }

  return (
    <>
      <header>
        <h1>API 设置</h1>
        <p>国内环境优先：默认 DeepSeek + 阿里云 ASR，也可接通义千问或本地兼容服务。</p>
      </header>
      <section className="settings-grid">
        <div className="panel settings-panel">
          <h2>AI API</h2>
          <label>预设</label>
          <select value={draft.ai_preset ?? "deepseek"} onChange={(event) => setValue("ai_preset", event.target.value)}>
            <option value="deepseek">DeepSeek</option>
            <option value="qwen">通义千问兼容</option>
            <option value="local">本地兼容服务</option>
            <option value="custom">自定义兼容接口</option>
          </select>
          <label>Base URL</label>
          <input value={draft.ai_base_url ?? ""} onChange={(event) => setValue("ai_base_url", event.target.value)} />
          <label>API Key</label>
          <input value={draft.ai_api_key ?? ""} onChange={(event) => setValue("ai_api_key", event.target.value)} placeholder="本地服务可留空" />
          <label>模型名</label>
          <input value={draft.ai_model ?? ""} onChange={(event) => setValue("ai_model", event.target.value)} />
          <label className="inline-check">
            <input type="checkbox" checked={draft.ai_json_mode === "true"} onChange={(event) => setValue("ai_json_mode", String(event.target.checked))} />
            启用 JSON 模式
          </label>
          <p className="field-hint">让 AI 按程序可识别的格式返回结果，语义切分和方案生成更稳定；如果某些兼容接口报错，再关闭。</p>
          <p className="field-hint">填完 API Key 后要点“保存设置”，再点“测试 AI”。本地兼容服务可以留空，DeepSeek/通义云端不能留空。</p>
          <div className="action-row">
            <button className="secondary" onClick={() => test("ai")}>测试 AI</button>
            <button className="primary-action" onClick={save}>保存设置</button>
          </div>
        </div>
        <div className="panel settings-panel">
          <h2>ASR API</h2>
          <label>提供商</label>
          <select value={draft.asr_provider ?? "local_whisper"} onChange={(event) => setValue("asr_provider", event.target.value)}>
            <option value="local_whisper">本地 Whisper.cpp（推荐）</option>
            <option value="aliyun_nls">阿里云 NLS</option>
            <option value="whisper_compatible">Whisper 兼容 ASR</option>
            <option value="manual_transcript">手动转录</option>
          </select>
          <label>Whisper 命令路径</label>
          <input value={draft.local_whisper_binary_path ?? ""} onChange={(event) => setValue("local_whisper_binary_path", event.target.value)} placeholder="留空自动查找 whisper-cli" />
          <label>Whisper 模型路径</label>
          <input value={draft.local_whisper_model_path ?? ""} onChange={(event) => setValue("local_whisper_model_path", event.target.value)} placeholder="例如 ggml-large-v3-turbo.bin 的本地路径" />
          <label>识别语言</label>
          <input value={draft.local_whisper_language ?? "zh"} onChange={(event) => setValue("local_whisper_language", event.target.value)} placeholder="中文填 zh，自动识别可填 auto" />
          <p className="field-hint">本地运行 whisper.cpp，不上传音频；如果测试提示缺少命令，可安装 brew install whisper-cpp。</p>
          <label>阿里云 AccessKey ID</label>
          <input value={draft.aliyun_access_key_id ?? ""} onChange={(event) => setValue("aliyun_access_key_id", event.target.value)} />
          <label>阿里云 AccessKey Secret</label>
          <input value={draft.aliyun_access_key_secret ?? ""} onChange={(event) => setValue("aliyun_access_key_secret", event.target.value)} />
          <label>NLS AppKey</label>
          <input value={draft.aliyun_app_key ?? ""} onChange={(event) => setValue("aliyun_app_key", event.target.value)} />
          <label>兼容 ASR Base URL</label>
          <input value={draft.asr_base_url ?? ""} onChange={(event) => setValue("asr_base_url", event.target.value)} />
          <label>兼容 ASR 模型名</label>
          <input value={draft.asr_model ?? ""} onChange={(event) => setValue("asr_model", event.target.value)} />
          <div className="action-row">
            <button className="secondary" onClick={() => test("asr")}>测试 ASR</button>
            <button className="primary-action" onClick={save}>保存设置</button>
          </div>
        </div>
        <div className="panel settings-panel">
          <h2>TTS API</h2>
          <label>兼容 TTS Base URL</label>
          <input value={draft.tts_base_url ?? ""} onChange={(event) => setValue("tts_base_url", event.target.value)} placeholder="例如 OpenAI/Qwen 兼容语音服务地址" />
          <label>TTS API Key</label>
          <input value={draft.tts_api_key ?? ""} onChange={(event) => setValue("tts_api_key", event.target.value)} placeholder="本地服务可留空" />
          <label>TTS 模型名</label>
          <input value={draft.tts_model ?? ""} onChange={(event) => setValue("tts_model", event.target.value)} placeholder="例如 qwen-tts 或兼容模型名" />
          <label>默认音色</label>
          <input value={draft.tts_voice ?? "alloy"} onChange={(event) => setValue("tts_voice", event.target.value)} />
          <label>音频格式</label>
          <select value={draft.tts_format ?? "mp3"} onChange={(event) => setValue("tts_format", event.target.value)}>
            <option value="mp3">mp3</option>
            <option value="wav">wav</option>
            <option value="aac">aac</option>
            <option value="opus">opus</option>
          </select>
          <p className="field-hint">没有配置 TTS 时，配音中心会生成静音占位音频，方便先验证“文案语义填充素材”的完整流程。</p>
          <div className="action-row">
            <button className="secondary" onClick={() => test("tts")}>测试 TTS</button>
            <button className="primary-action" onClick={save}>保存设置</button>
          </div>
        </div>
      </section>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
