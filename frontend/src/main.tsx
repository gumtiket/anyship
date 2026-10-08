import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowRight, Check, ChevronRight, ExternalLink, FolderGit2, GitBranch, Github, GitPullRequest, Layers3, LoaderCircle, LogOut, Plus, ShieldCheck, Sparkles, X } from 'lucide-react';
import './style.css';
import './workflow.css';
import { ChangeWorkflow } from './ChangeWorkflow';
import { RepositoryConnect } from './RepositoryConnect';
import { api, ApiError, mutation, type ConnectionDraft, type Project } from './api';

type Config = { demo: boolean; github_configured: boolean; ai_mode: string };
type Me = { user: { name: string; login: string }; workspace: { id: string; name: string }; csrf_token: string };
const authErrors: Record<string, string> = {
  incorrect_client_credentials: '현재 GitHub 로그인 연결에 문제가 있습니다. 잠시 후 다시 시도하고, 반복되면 서비스 관리자에게 알려주세요.',
  redirect_uri_mismatch: '현재 GitHub 로그인 연결에 문제가 있습니다. 서비스 관리자에게 알려주세요.',
  invalid_state: '로그인 요청이 만료되었거나 시작한 브라우저와 다릅니다. 다시 로그인해 주세요.',
  bad_verification_code: 'GitHub 로그인 요청이 만료되었습니다. 다시 로그인해 주세요.',
  incorrect_code_verifier: '로그인 요청을 확인하지 못했습니다. 다시 로그인해 주세요.',
  access_denied: 'GitHub 로그인이 취소되었습니다. 준비되면 다시 시작해 주세요.',
  missing_code: 'GitHub 로그인 응답을 확인하지 못했습니다. 다시 로그인해 주세요.',
  not_configured: '지금은 GitHub 로그인을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
  network_error: 'GitHub에 연결하지 못했습니다. 잠시 후 다시 로그인해 주세요.',
};
const initialQuery = new URLSearchParams(location.search);
const returnedFromGitHub = initialQuery.has('setup_action') || initialQuery.has('installation_id') || initialQuery.has('state');

function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsReady, setProjectsReady] = useState(false);
  const [route, setRoute] = useState(returnedFromGitHub ? 'connect' : location.hash.slice(1) || 'projects');
  const [returnState, setReturnState] = useState(initialQuery.get('state'));
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const detail = route.startsWith('project/') ? projects.find(p => p.id === route.slice(8)) : null;
  const screen = route === 'connect' ? 'connect' : route.startsWith('project/') ? 'detail' : 'projects';

  function navigate(next: string) { setRoute(next); location.hash = next; setError(''); }
  function sessionError(e: unknown) {
    if (e instanceof ApiError && e.status === 401) { setMe(null); setProjects([]); setProjectsReady(false); }
  }
  function report(e: unknown) { sessionError(e); setError(e instanceof Error ? e.message : '연결에 실패했습니다.'); }
  async function refreshProjects() { setProjects(await api<Project[]>('/projects')); }

  useEffect(() => {
    const changed = () => { setRoute(location.hash.slice(1) || 'projects'); setError(''); };
    window.addEventListener('hashchange', changed);
    (async () => {
      try {
        const value = await api<Config>('/config'); setConfig(value);
        if (!value.demo) {
          try { setMe(await api<Me>('/me')); } catch (e) { if (!(e instanceof ApiError && e.status === 401)) throw e; }
        }
      } catch (e) { report(e); } finally { setReady(true); }
      const authError = initialQuery.get('auth_error');
      if (authError) setError(authErrors[authError] ?? 'GitHub 로그인 확인에 실패했습니다. 다시 시도해 주세요.');
      // Strip callback data from the address bar; only the local route remains.
      if (location.search) history.replaceState(null, '', '/' + (returnedFromGitHub ? '#connect' : location.hash));
    })();
    return () => window.removeEventListener('hashchange', changed);
  }, []);

  useEffect(() => {
    if (!me) return;
    let active = true;
    setProjectsReady(false);
    (async () => {
      try {
        const [items, pending] = await Promise.all([api<Project[]>('/projects'), api<ConnectionDraft | null>('/github/connection')]);
        if (!active) return;
        setProjects(items);
        if (!location.hash && pending) navigate('connect');
      } catch (e) { if (active) report(e); }
      finally { if (active) setProjectsReady(true); }
    })();
    return () => { active = false; };
  }, [me]);

  async function openConnected(projectId: string) { await refreshProjects(); navigate('project/' + projectId); }
  async function logout() {
    if (!me) return;
    setBusy(true);
    try {
      await api('/auth/logout', mutation(me.csrf_token)); setMe(null); setProjects([]); setReturnState(null);
      navigate('projects');
    } catch (e) { report(e); } finally { setBusy(false); }
  }
  const alert = error && <div className="error" role="alert"><span>{error}</span><button aria-label="알림 닫기" onClick={() => setError('')}><X size={16}/></button></div>;
  if (!ready) return <main className="loading"><LoaderCircle className="spin"/> AnyShip을 불러오고 있습니다.</main>;
  if (!me) return <div className="landing">
    <header className="landing-header"><Brand/><span className="quiet">Your code. Ready to ship.</span></header>
    <main className="landing-main"><section className="intro"><span className="eyebrow">FROM REPOSITORY TO PULL REQUEST</span><h1>코드의 다음 단계,<br/><em>AnyShip과 함께.</em></h1><p>저장소 주소로 시작하고,<br/>검토한 변경을 GitHub PR로 연결하세요.</p>
      <div className="intro-steps"><span><Github size={18}/> 저장소 연결</span><ChevronRight size={14}/><span><Sparkles size={18}/> 분석 · 수정</span><ChevronRight size={14}/><span><GitPullRequest size={18}/> 변경 검토 · PR</span></div>
      <div className="soon-note">{config?.ai_mode === 'placeholder' ? '현재는 테스트 모드입니다. AI 대신 안내 파일을 추가해 실제 PR 흐름을 확인합니다.' : 'AI 분석 기능은 준비 중입니다. 저장소 연결부터 시작할 수 있습니다.'}</div></section>
      <section className="login-card"><div className="icon-box"><Github size={26}/></div><h2>AnyShip 시작하기</h2><p>GitHub 계정으로 가입하고 로그인합니다.<br/>다음 단계에서 저장소 주소를 입력하세요.</p>{alert}
        {config?.github_configured && !config.demo ? <a className="primary full" href="/api/auth/github/start"><Github size={18}/> GitHub로 시작하기</a> : <><button className="primary full" disabled>현재 로그인 준비 중입니다</button><p className="helper">서비스 연결을 준비하고 있습니다. 잠시 후 다시 방문해 주세요.</p></>}
        <div className="login-foot"><ShieldCheck size={16}/> 원하는 저장소만 연결할 수 있습니다.</div>
      </section></main><footer className="landing-footer">AnyShip<span>GitHub 연결 · 변경 검토 · Draft PR</span></footer>
  </div>;

  return <div className="shell"><aside className="sidebar"><Brand/><div className="workspace-avatar"><span>{me.user.login.slice(0, 1).toUpperCase()}</span><div><strong>개인 워크스페이스</strong><small>@{me.user.login}</small></div></div>
    <div className="nav-label">WORKSPACE</div><nav><button className={screen !== 'connect' ? 'active' : ''} onClick={() => navigate('projects')}><Layers3 size={18}/> 프로젝트 <span className="count">{projects.length}</span></button><button className={screen === 'connect' ? 'active' : ''} onClick={() => navigate('connect')}><Github size={18}/> 저장소 연결</button></nav>
    <div className="sidebar-foot"><div className="local-status">{config?.ai_mode === 'placeholder' ? '테스트 모드 · AI 임시 항목 사용' : 'AI 분석 기능 준비 중'}</div><button className="logout" disabled={busy} onClick={logout}><LogOut size={16}/> 로그아웃</button></div></aside>
    <div className="main-area"><header className="app-header"><span>개인 워크스페이스 <ChevronRight size={14}/> {screen === 'projects' ? '프로젝트' : screen === 'connect' ? '저장소 연결' : detail?.full_name.split('/').pop() ?? '프로젝트'}</span><span className="avatar">{me.user.name.slice(0, 1)}</span></header>
    <main className="content">{alert}
      {!projectsReady ? <p role="status"><LoaderCircle size={16} className="spin"/> 내 프로젝트를 불러오고 있습니다.</p> : <>
        {screen === 'projects' && <><div className="page-heading"><div><span className="eyebrow">YOUR WORKSPACE</span><h1>내 프로젝트</h1><p>저장소에서 시작해 검토 가능한 PR까지.</p></div><button className="primary" onClick={() => navigate('connect')}><Plus size={17}/> 프로젝트 연결</button></div>
          {projects.length === 0 ? <div className="empty-state"><div className="empty-art"><FolderGit2 size={40}/><span className="tiny-plus">+</span></div><h2>첫 프로젝트를 연결해 보세요</h2><p>GitHub 저장소 주소만 준비하세요.<br/>접근 승인부터 브랜치 선택까지 안내합니다.</p><button className="primary" onClick={() => navigate('connect')}><Github size={18}/> 저장소 URL로 연결</button></div> : <div className="project-grid">{projects.map(project => <button className="project-card" key={project.id} onClick={() => navigate('project/' + project.id)}><div className="project-card-top"><FolderGit2 size={22}/><span className="status"><Check size={12}/> 등록됨</span></div><h2>{project.full_name.split('/').pop()}</h2><p>{project.full_name}</p><div className="project-card-bottom"><span><GitBranch size={14}/> {project.branch}</span><ArrowRight size={17}/></div></button>)}</div>}
          <div className="roadmap"><div><span className="step-number">01</span><h3>저장소 연결</h3><p>주소와 접근 권한을 확인합니다.</p></div><div><span className="step-number">02</span><h3>수정 항목 실행</h3><p>{config?.ai_mode === 'placeholder' ? '테스트에서는 임시 수정 항목을 사용합니다.' : 'AI 분석 기능은 준비 중입니다.'}</p></div><div><span className="step-number">03</span><h3>변경 검토 · PR</h3><p>내용을 확인하고 GitHub에 제출합니다.</p></div></div>
        </>}
        {screen === 'connect' && <RepositoryConnect csrf={me.csrf_token} returnState={returnState} onReturnHandled={() => setReturnState(null)} onConnected={openConnected} onError={sessionError}/>}
        {screen === 'detail' && (detail ? <><div className="page-heading"><div><span className="eyebrow">PROJECT</span><h1>{detail.full_name.split('/').pop()}</h1><a className="text-link" href={`https://github.com/${detail.full_name}`} target="_blank" rel="noreferrer">{detail.full_name} <ExternalLink size={13}/></a></div><span className="status"><GitBranch size={14}/> {detail.branch}</span></div><ChangeWorkflow key={detail.id} projectId={detail.id} csrf={me.csrf_token} aiMode={config?.ai_mode ?? 'unavailable'} request={api} onError={sessionError}/><button className="text-link" onClick={() => navigate('projects')}>프로젝트 목록으로 돌아가기 <ArrowRight size={15}/></button></> : <div className="empty-state"><h2>프로젝트를 찾을 수 없습니다</h2><p>현재 계정에서 접근할 수 있는 프로젝트를 확인해 주세요.</p><button className="secondary" onClick={() => navigate('projects')}>내 프로젝트 보기</button></div>)}
      </>}
    </main><footer className="app-footer">AnyShip<span>변경은 검토하고, 배포는 다음 단계로.</span></footer></div>
  </div>;
}
function Brand() { return <div className="brand"><span><Layers3 size={19}/></span> AnyShip</div>; }
createRoot(document.getElementById('root')!).render(<App/>);
