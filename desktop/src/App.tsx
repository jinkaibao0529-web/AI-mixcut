import { type KeyboardEvent, type RefObject, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE_URL = "http://127.0.0.1:8000/api";
const SEGMENT_TYPES = ["噱头引入", "痛点", "产品方案", "效果展示", "信任背书", "价格对比", "活动福利", "行动号召", "产品定位", "过渡"];
const POSITION_TYPES = ["开头", "中间", "结尾"];
const SIDEBAR_CATEGORY_LIMIT = 4;
const SCHEME_PREVIEW_START_GUARD_SECONDS = 0.06;
const SCHEME_PREVIEW_END_GUARD_SECONDS = 0.02;

type WorkspaceView = "workspace" | "overview" | "import" | "segments" | "schemes" | "settings";

type Project = {
  id: number;
  name: string;
  category: string;
  custom_prompt: string;
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
        {message && <p className="notice">{message}</p>}
        {error && <pre className="error panel">{error}</pre>}

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
            {view === "segments" && <SegmentLibrary segments={segments} videos={videos} onRefresh={() => loadProjectData(activeProject.id)} setError={setError} setMessage={setMessage} />}
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
    ["segments", "片段库"],
    ["schemes", "混剪方案"],
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
  return (
    <section className="overview-grid">
      <MetricCard label="视频" value={props.videos.length} />
      <MetricCard label="语义片段" value={props.segments.length} />
      <MetricCard label="混剪方案" value={props.schemes.length} />
      <div className="panel overview-panel">
        <h2>最近视频</h2>
        {props.videos.slice(0, 5).map((video) => (
          <div className="compact-row" key={video.id}>
            <span>{video.name}</span>
            <strong>{video.status}</strong>
          </div>
        ))}
        {props.videos.length === 0 && <p className="empty">还没有导入视频。</p>}
      </div>
    </section>
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
  const [files, setFiles] = useState<File[]>([]);
  const [importing, setImporting] = useState(false);
  const [reanalyzingId, setReanalyzingId] = useState<number | null>(null);

  async function uploadVideo() {
    if (files.length === 0) {
      props.setError("请先选择一个或多个视频。");
      return;
    }
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    setImporting(true);
    try {
      await fetch(`${API_BASE_URL}/projects/${props.project.id}/videos/import`, { method: "POST", body: formData }).then(async (response) => {
        if (!response.ok) throw new Error((await response.json()).detail ?? "导入失败");
      });
      setFiles([]);
      props.setMessage(`已导入 ${files.length} 个视频，后台正在自动转录和切分。`);
      props.onRefresh();
    } catch (err) {
      props.setError(err instanceof Error ? err.message : "未知错误");
    } finally {
      setImporting(false);
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

  return (
    <>
      <div className="view-sticky-head import-sticky-head">
        <section className="panel upload-panel">
          <div className="upload-field">
            <label>导入视频</label>
            <input
              id="video-file-input"
              className="file-input-hidden"
              type="file"
              accept="video/*"
              multiple
              onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            />
            <div className="file-picker-row">
              <label className="file-picker-button" htmlFor="video-file-input">选择视频文件</label>
              <p className={files.length > 0 ? "file-picker-status active" : "file-picker-status"}>
                {files.length > 0 ? `已选择 ${files.length} 个视频，导入后会自动转录和语义切分。` : "未选择文件"}
              </p>
            </div>
          </div>
          <button className="primary-action" disabled={importing} onClick={uploadVideo}>
            {importing ? "导入中..." : "自动分析"}
          </button>
        </section>
      </div>

      <section className="video-grid">
        {props.videos.map((video) => {
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
      </section>
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
          {orderedTags.map(([tag, count]) => (
            <span className={`tag-chip tag-count-chip ${tagColorClass(tag)}`} key={tag}>{tag} {count}</span>
          ))}
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
  return (value ?? "").split(",").map((item) => item.trim()).filter(Boolean);
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

function tagColorClass(tag: string) {
  const index = SEGMENT_TYPES.indexOf(tag);
  return index >= 0 ? `tag-color-${index}` : "tag-color-default";
}

function TagChip(props: { tag: string; className?: string }) {
  return <span className={`tag-chip ${tagColorClass(props.tag)} ${props.className ?? ""}`.trim()}>{props.tag}</span>;
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

function SegmentLibrary(props: { segments: Segment[]; videos: VideoItem[]; onRefresh: () => void; setError: (value: string) => void; setMessage: (value: string) => void }) {
  useCloseTagMenusOnOutsideClick();
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
  const filtered = props.segments
    .filter((segment) => (tagFilters.length === 0 || tagFilters.some((tag) => multiValueIncludes(segment.semantic_type, tag))) && (!position || multiValueIncludes(segment.position_type, position)))
    .filter((segment) => !query.trim() || `${segment.text} ${segment.video_name} ${segment.semantic_type}`.toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a, b) => {
      if (sortMode === "duration") return (b.end_seconds - b.start_seconds) - (a.end_seconds - a.start_seconds);
      return a.video_name.localeCompare(b.video_name) || a.start_seconds - b.start_seconds;
    });
  const selected = props.segments.find((segment) => segment.id === selectedId) ?? filtered[0] ?? null;
  const tagCounts = SEGMENT_TYPES.map((tag) => ({
    tag,
    count: props.segments.filter((segment) => multiValueIncludes(segment.semantic_type, tag)).length,
  }));
  const groupedSegments = filtered.reduce<Record<string, Segment[]>>((groups, segment) => {
    groups[segment.video_name] = groups[segment.video_name] ?? [];
    groups[segment.video_name].push(segment);
    return groups;
  }, {});

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
      text: draft.text ?? selected.text,
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

  async function exportSegmentIds(segmentIds: number[]) {
    if (segmentIds.length === 0) {
      props.setError("请先选择要导出的片段。");
      return;
    }
    try {
      const result = await api<{ export_paths: string[]; export_root?: string }>("/segments/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ segment_ids: segmentIds, output_dir: exportDir || undefined }),
      });
      props.setMessage(`已导出 ${result.export_paths.length} 个素材，已按语义 tag 放入项目文件夹：${result.export_root || result.export_paths.join("；")}`);
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
            全部 {props.segments.length}
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

        <section className="export-bar">
          <button className="secondary" onClick={chooseExportDir}>选择保存路径</button>
          <span>{exportDir || "未选择时默认保存到 data/exports"}</span>
          <button className="secondary" disabled={deduping || props.segments.length === 0} onClick={dedupeSegments}>
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
          <p className="segment-count">{filtered.length} / {props.segments.length} 个分镜</p>
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
          {filtered.length === 0 && <p className="empty panel">暂无片段。</p>}
        </div>

        <aside className="panel segment-editor">
          {selected ? (
            <>
              <div className="section-title">
                <div>
                  <h2>片段微调</h2>
                  <p>{selected.video_name}</p>
                </div>
                <button className="primary-action" onClick={saveSegment}>保存</button>
              </div>
              <div className="large-preview-shell">
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
              <div className="micro-controls">
                <button onClick={() => nudgeSegment(selected, "start", -0.1)}>入-</button>
                <button onClick={() => nudgeSegment(selected, "start", 0.1)}>入+</button>
                <button onClick={() => nudgeSegment(selected, "end", -0.1)}>出-</button>
                <button onClick={() => nudgeSegment(selected, "end", 0.1)}>出+</button>
              </div>
              <div className="edit-grid compact">
                <MultiValueEditor
                  label="Tag"
                  options={SEGMENT_TYPES}
                  values={splitMultiValue(draft.semantic_type ?? selected.semantic_type)}
                  onChange={(values) => setDraft((current) => ({ ...current, semantic_type: joinMultiValue(values) }))}
                />
                <MultiValueEditor
                  label="位置"
                  options={POSITION_TYPES}
                  values={splitMultiValue(draft.position_type ?? selected.position_type)}
                  onChange={(values) => setDraft((current) => ({ ...current, position_type: joinMultiValue(values) }))}
                />
                <label>开始秒
                  <input type="number" step="0.1" value={draft.start_seconds ?? selected.start_seconds} onChange={(event) => setDraft((current) => ({ ...current, start_seconds: Number(event.target.value) }))} />
                </label>
                <label>结束秒
                  <input type="number" step="0.1" value={draft.end_seconds ?? selected.end_seconds} onChange={(event) => setDraft((current) => ({ ...current, end_seconds: Number(event.target.value) }))} />
                </label>
              </div>
              <label>台词文案
                <textarea value={draft.text ?? selected.text} onChange={(event) => setDraft((current) => ({ ...current, text: event.target.value }))} rows={8} />
              </label>
              <div className="tag-line">
                <span>{formatClockPrecise(selected.start_seconds)} - {formatClockPrecise(selected.end_seconds)}</span>
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
        <strong>{props.values.length > 0 ? props.values.join(" / ") : "未选择"}</strong>
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

function SegmentCard(props: {
  segment: Segment;
  active: boolean;
  index: number;
  viewMode: "grid" | "list";
  selectedForExport: boolean;
  onSelect: () => void;
  onNudge: (segment: Segment, boundary: "start" | "end", delta: number) => void;
  onTagsChange: (segment: Segment, field: "semantic_type" | "position_type", values: string[]) => void;
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
        <div className="segment-type-line">{splitMultiValue(props.segment.semantic_type).map((tag) => <TagChip key={tag} tag={tag} />)}</div>
        <small>{formatClock(props.segment.start_seconds)} · 台词 {props.segment.text.length}字</small>
        <p>{props.segment.text || "无转录文本"}</p>
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
        <strong>{props.values.length > 0 ? props.values.join(" / ") : "未选择"}</strong>
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

  async function test(target: "ai" | "asr") {
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
      </section>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
