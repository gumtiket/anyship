import { useEffect, useRef, useState } from 'react';
import { Check, FileCode2, LoaderCircle, RefreshCw, Sparkles } from 'lucide-react';
import { api, mutation } from './api';

type Warning = { code: string; message: string };
type Finding = { id: string; file: string; line: number; evidence: string; description?: string; rule: string; change_class: string };
type Result = {
  analysis_status: string; llm_mode: string; execution_source: string;
  diagnosis: { support_grade: string; framework?: { reason: string }; violations: Finding[]; warnings: Warning[] };
  transformation: { status: string; needs_approval: boolean; addressed_ids: string[]; deferred_ids: string[]; warnings: Warning[] };
  recommendation: { set?: string; rationale?: string; estimated_monthly_cost?: number | null; needs_confirmation: string[]; assumptions: string[] };
  gate: { status: string; pr_eligible: boolean; historical_status?: string; reason: string };
  cost: { historical: boolean; external_calls?: number | null; total: { cost_usd: number | null; input_tokens: number; output_tokens: number } };
  bundle: { id: string; paths: string[]; patch_valid: boolean };
  artifacts: Record<string, string>;
  source: { file_count: number; excluded_count: number };
};
type Job = { id: string; status: string; base_sha: string; created_at: number; error: string; busy: boolean; result?: Result; diff?: string; review_hash?: string; logs?: { ts: number; message: string }[] };
type Props = { projectId: string; csrf: string; onError: (error: unknown) => void };
const labels: Record<string, string> = { queued: '대기', running: '분석 중', completed: '결과 생성', reviewed: '검토 기록 완료', failed: '실패', interrupted: '중단', diagnosed: '진단 완료', partial: '부분 지원·일부 보류', unsupported: '지원하지 않는 구조' };

export function AIAnalysis({ projectId, csrf, onError }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(false);
  const requestId = useRef<string | null>(null);
  const endpoint = `/projects/${projectId}/ai-analyses`;
  const selectedJobId = useRef<string | null>(null);
  const mounted = useRef(true);
  function report(e: unknown) { if (!mounted.current) return; setError(e instanceof Error ? e.message : '작업을 처리하지 못했습니다.'); onError(e); }
  async function choose(id: string) {
    selectedJobId.current = id; setSelected(false); setError('');
    try { const value = await api<Job>(`${endpoint}/${id}`); if (mounted.current && selectedJobId.current === id) setJob(value); } catch (e) { report(e); }
  }
  useEffect(() => {
    mounted.current = true;
    api<Job[]>(endpoint).then(async values => {
      if (!mounted.current) return;
      setJobs(values);
      if (values[0]) await choose(values[0].id);
    }).catch(report).finally(() => { if (mounted.current) setLoading(false); });
    return () => { mounted.current = false; };
  }, [endpoint]);
  useEffect(() => {
    if (!job?.busy) return;
    const id = job.id;
    let active = true;
    const timer = setInterval(async () => {
      try {
        const value = await api<Job>(`${endpoint}/${id}`);
        if (!active || selectedJobId.current !== id) return;
        setJobs(values => values.map(item => item.id === id ? value : item));
        setJob(value);
      } catch (e) { if (active) report(e); }
    }, 1500);
    return () => { active = false; clearInterval(timer); };
  }, [endpoint, job?.id, job?.busy]);
  async function start() {
    setBusy(true); setError(''); setSelected(false);
    requestId.current ??= crypto.randomUUID();
    try {
      const value = await api<Job>(endpoint, mutation(csrf, { request_id: requestId.current }));
      if (!mounted.current) return;
      requestId.current = null;
      selectedJobId.current = value.id; setJob(value);
      setJobs(await api<Job[]>(endpoint));
    } catch (e) { report(e); } finally { if (mounted.current) setBusy(false); }
  }
  async function review() {
    if (!job) return;
    setBusy(true); setError('');
    try {
      const value = await api<Job>(`${endpoint}/${job.id}/review`, mutation(csrf, { review_hash: job.review_hash, selected_bundle_ids: ['all-changes'] }));
      if (mounted.current) { setJob(value); setSelected(false); setJobs(await api<Job[]>(endpoint)); }
    } catch (e) { report(e); } finally { if (mounted.current) setBusy(false); }
  }
  const result = job?.result?.diagnosis ? job.result : undefined;
  const waiting = busy || Boolean(job?.busy);
  const warnings = result ? [...new Map([...result.diagnosis.warnings, ...result.transformation.warnings].map(w => [w.code, w])).values()] : [];
  return <section className="panel change-workflow" aria-label="Fake AI 연결 검증">
    <div className="panel-heading"><h2><Sparkles size={18}/> AI 분석 · 수정안 검토</h2><span className="status">Fake · 연결 검증</span></div>
    <p className="workflow-description">기준 커밋의 코드를 AI 분석기에 전달합니다. 모델 응답은 사전 준비된 값을 사용하며, 앱 실행 검증은 생략합니다. 선택과 검토 기록까지 진행할 수 있습니다.</p>
    <button className="primary" disabled={loading || waiting || jobs.some(item => item.busy)} onClick={start}><RefreshCw size={16}/> {requestId.current ? '같은 분석 요청 다시 확인' : '기준 커밋으로 새 분석'}</button>
    {jobs.length > 0 && <label className="ai-history">분석 이력<select aria-label="분석 이력" disabled={loading || waiting} value={job?.id ?? ''} onChange={e => choose(e.target.value)}>{jobs.map(item => <option key={item.id} value={item.id}>{new Date(item.created_at * 1000).toLocaleString('ko-KR')} · {labels[item.status] ?? item.status} · {item.base_sha.slice(0, 8)}</option>)}</select></label>}
    {error && <p className="error" role="alert">{error}</p>}
    {job?.error && <p className="error" role="alert">{job.error}</p>}
    <div aria-live="polite">{(loading || waiting) && <p className="workflow-busy"><LoaderCircle size={16} className="spin"/> {loading ? '분석 이력을 불러옵니다.' : '기준 코드 확인·분석 중입니다. 새로고침 후에도 작업을 확인할 수 있습니다.'}</p>}</div>
    {job && <p className="small quiet">{labels[job.status] ?? job.status} · 기준 커밋 <code>{job.base_sha}</code></p>}
    {!!job?.logs?.length && <details open={Boolean(job.busy)}><summary>진행 기록</summary><ol>{job.logs.map((entry, i) => <li key={i}>{entry.message}</li>)}</ol></details>}
    {result && <>
      <div className="ai-result-summary"><strong>{labels[result.analysis_status] ?? result.analysis_status}</strong><p>{result.diagnosis.framework?.reason}</p><p>수정안: {result.transformation.status === 'partial' ? '일부 반영 · 나머지 보류' : result.transformation.status} · 반영 {result.transformation.addressed_ids.length}건 · 보류 {result.transformation.deferred_ids.length}건</p><p>코드 {result.source.file_count}개 · 제외 {result.source.excluded_count}개</p></div>
      <p className="ai-notice">실행 검증: 생략 · PR 승인 가능: 아니요. {result.gate.reason}{result.gate.historical_status && ` 과거 검증: ${result.gate.historical_status}.`}</p>
      {result.transformation.needs_approval && <p className="ai-notice">위험한 변경이 포함되어 사용자 승인이 필요합니다. 아래 검토 기록은 PR 게시나 배포 승인이 아닙니다.</p>}
      {warnings.length > 0 && <details open><summary>주의·보류 사항 {warnings.length}건</summary><ul>{warnings.map(w => <li key={w.code}>{w.message} <small className="quiet">({w.code})</small></li>)}</ul></details>}
      <details open><summary>진단 항목 {result.diagnosis.violations.length}건</summary>{result.diagnosis.violations.map(v => <article className="ai-finding" key={v.id}><strong>{v.description || v.rule}</strong><p><code>{v.file}:{v.line}</code> · {v.change_class === 'risky' ? '위험 변경' : '일반 변경'} · {result.transformation.addressed_ids.includes(v.id) ? '수정안 반영' : '보류'}</p><pre>{v.evidence}</pre></article>)}</details>
      <details><summary>배포 추천·비용</summary><p>{result.recommendation.set || '추천 없음'} · {result.recommendation.rationale}</p><p>인프라 비용: {result.recommendation.estimated_monthly_cost == null ? '미확정' : `$${result.recommendation.estimated_monthly_cost}/월 (임시 추정치)`}</p><p>추가 확인: {result.recommendation.needs_confirmation.join(', ') || '없음'}</p><ul>{result.recommendation.assumptions.map((v, i) => <li key={i}>{v}</li>)}</ul><p>모델 응답: Fake · 출처: {result.execution_source} · {result.cost.historical ? '과거' : '현재'} 모델 사용 비용: {result.cost.total.cost_usd == null ? '미확정' : `$${result.cost.total.cost_usd}`}</p><p>토큰: 입력 {result.cost.total.input_tokens} / 출력 {result.cost.total.output_tokens}</p></details>
      {!!job?.diff && <div className="ai-bundle"><h3><FileCode2 size={17}/> 전체 수정안</h3><p>연관된 파일을 함께 검토합니다. 개별 진단 항목별 선택은 아직 지원하지 않습니다.</p><ul>{result.bundle.paths.map(path => <li key={path}><code>{path}</code></li>)}</ul><pre className="change-diff" aria-label="AI 코드 변경 내용">{job.diff}</pre>
        {job.status === 'reviewed' ? <p className="workflow-verification"><Check size={16}/> 전체 수정안 선택·검토 기록 완료</p> : job.review_hash && <><label className="review-check"><input type="checkbox" checked={selected} disabled={waiting} onChange={e => setSelected(e.target.checked)}/><span>전체 수정안 묶음을 선택하고 변경 내용과 위험·보류 사항을 확인했습니다.</span></label><button className="primary" disabled={waiting || !selected} onClick={review}>선택한 묶음 검토 기록</button></>}
      </div>}
      {Object.entries(result.artifacts).map(([name, value]) => <details key={name}><summary>{name} 제안</summary><pre className="change-diff">{value}</pre></details>)}
      <p className="small quiet">이 단계에서는 원본 코드 수정, GitHub PR 게시, 실제 빌드·배포를 실행하지 않습니다.</p>
    </>}
  </section>;
}
