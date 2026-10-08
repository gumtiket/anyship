import { useEffect, useRef, useState } from 'react';
import { Check, Cloud, ExternalLink, LoaderCircle, Plus, RefreshCw, ShieldCheck } from 'lucide-react';
import { api, mutation } from './api';
import './aws.css';

type Environment = {
  id: string; name: string; region: string; request_id: string;
  status: 'PENDING' | 'VERIFYING' | 'CONNECTED' | 'FAILED' | 'EXPIRED';
  cloudformation_url: string | null; role_arn: string | null; aws_account_id: string | null;
  error_code: string | null; expires_at: number; verified_at: number | null;
};
type Draft = { request_id: string; name: string; region: string };
type Props = {
  csrf: string; available: boolean; regions: string[]; workspaceKey: string;
  environmentId: string | null; onSelect: (id: string | null) => void; onError: (error: unknown) => void;
};
const labels: Record<Environment['status'], string> = {
  PENDING: '역할 생성 대기', VERIFYING: '검증 중', CONNECTED: '연결 완료', FAILED: '검증 실패', EXPIRED: '등록 만료',
};
function readDraft(key: string): Draft | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || 'null');
    return value && typeof value.name === 'string' && typeof value.region === 'string'
      && typeof value.request_id === 'string' ? value : null;
  } catch { return null; }
}
function cloudFormationUrl(value: string | null) {
  try {
    const url = new URL(value || '');
    return url.protocol === 'https:' && /^[a-z0-9-]+\.console\.aws\.amazon\.com$/.test(url.hostname) ? url.href : null;
  } catch { return null; }
}

export function AwsEnvironments({ csrf, available, regions, workspaceKey, environmentId, onSelect, onError }: Props) {
  const storageKey = `anyship.aws.draft:${workspaceKey}`;
  const [draft, setDraft] = useState<Draft | null>(() => readDraft(storageKey));
  const [name, setName] = useState(() => readDraft(storageKey)?.name || '');
  const [region, setRegion] = useState(() => readDraft(storageKey)?.region || regions[0] || '');
  const [rows, setRows] = useState<Environment[]>([]);
  const [selected, setSelected] = useState<Environment | null>(null);
  const [roleArn, setRoleArn] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const mounted = useRef(true), locked = useRef(false), revision = useRef(0);
  const activeId = useRef(environmentId);
  activeId.current = environmentId;

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; revision.current++; }; }, []);
  function report(e: unknown) {
    if (!mounted.current) return;
    onError(e); setError(e instanceof Error ? e.message : 'AWS 연결을 확인하지 못했습니다.');
  }
  function accept(row: Environment, replaceRole = true) {
    setSelected(row); setName(row.name); setRegion(row.region);
    if (replaceRole || row.role_arn) setRoleArn(row.role_arn || '');
  }
  async function load(id: string | null) {
    const version = ++revision.current;
    setLoading(true);
    try {
      const [items, row] = await Promise.all([
        api<Environment[]>('/aws/environments?limit=20'),
        id ? api<Environment>(`/aws/environments/${encodeURIComponent(id)}`) : Promise.resolve(null),
      ]);
      if (!mounted.current || version !== revision.current) return;
      setRows(items); setHasMore(items.length === 20);
      if (row) accept(row, selected?.id !== row.id);
      else setSelected(null);
    } catch (e) { if (version === revision.current) report(e); }
    finally { if (mounted.current && version === revision.current) setLoading(false); }
  }
  useEffect(() => {
    setError(''); setNotice(''); setSelected(null); setRoleArn('');
    if (!environmentId) {
      const pending = readDraft(storageKey); setDraft(pending);
      setName(pending?.name || ''); setRegion(pending?.region || regions[0] || '');
    }
    void load(environmentId);
  }, [environmentId]);

  async function perform(operation: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(''); setNotice('');
    try { await operation(); } catch (e) { report(e); }
    finally { locked.current = false; if (mounted.current) setBusy(false); }
  }
  async function register() {
    await perform(async () => {
      const body = draft || { request_id: crypto.randomUUID(), name: name.trim(), region };
      if (!body.name || !body.region) throw new Error('환경 이름과 리전을 입력해 주세요.');
      // Save before the request so a lost response can be retried without duplicating the environment.
      sessionStorage.setItem(storageKey, JSON.stringify(body)); setDraft(body);
      const row = await api<Environment>('/aws/environments', mutation(csrf, body));
      if (!mounted.current) return;
      sessionStorage.removeItem(storageKey); setDraft(null); accept(row); onSelect(row.id);
    });
  }
  async function verify() {
    if (!selected) return;
    const id = selected.id;
    await perform(async () => {
      try {
        const row = await api<Environment>(`/aws/environments/${id}/verify`, mutation(csrf, { role_arn: roleArn.trim() }));
        if (!mounted.current || activeId.current !== id) return;
        accept(row); setRows(items => items.map(item => item.id === row.id ? row : item));
        setNotice('AWS 계정이 연결됐습니다. 검증한 역할과 계정 정보가 저장됐습니다.');
      } catch (e) {
        try {
          const row = await api<Environment>(`/aws/environments/${id}`);
          if (mounted.current && activeId.current === id) {
            accept(row, false); setRows(items => items.map(item => item.id === row.id ? row : item));
          }
        } catch { /* Preserve the verification error. */ }
        throw e;
      }
    });
  }
  async function more() {
    await perform(async () => {
      const items = await api<Environment[]>(`/aws/environments?limit=20&offset=${rows.length}`);
      if (mounted.current) { setRows(previous => [...previous, ...items]); setHasMore(items.length === 20); }
    });
  }
  function startNew() {
    if (locked.current) return;
    sessionStorage.removeItem(storageKey); setDraft(null); setSelected(null); setRoleArn('');
    setName(''); setRegion(regions[0] || ''); setError(''); setNotice(''); onSelect(null);
  }
  const ready = !loading && !busy, connected = selected?.status === 'CONNECTED';
  const url = cloudFormationUrl(selected?.cloudformation_url || null);
  const canVerify = available && ready && selected && ['PENDING', 'FAILED'].includes(selected.status);
  const supportedRegions = [...new Set([...regions, ...(selected ? [selected.region] : [])])];

  return <div className="aws-page">
    <div className="page-heading"><div><span className="eyebrow">CLOUD ENVIRONMENTS</span><h1>AWS 환경</h1><p>내 AWS 계정의 역할을 연결하고 연결 상태를 확인하세요.</p></div>
      <button className="secondary" disabled={!ready} onClick={() => { setError(''); void load(environmentId); }}><RefreshCw size={15}/> 상태 새로고침</button>
    </div>
    {!available && <div className="aws-setup" role="status"><Cloud size={20}/><div><strong>AWS 연결을 준비하고 있습니다</strong><p>서비스의 AWS 연결 설정이 완료되면 새 환경을 등록할 수 있습니다. 기존 연결 정보는 아래에서 확인할 수 있습니다.</p></div></div>}
    {error && <div className="error" role="alert">{error}</div>}
    {notice && <p className="resume-note" role="status"><Check size={16}/>{notice}</p>}
    <ol className="connection-steps" aria-label="AWS 환경 연결 단계">
      <li className={selected ? 'done' : 'current'}><span>{selected ? <Check size={14}/> : '1'}</span> 환경 등록</li>
      <li className={connected ? 'done' : selected ? 'current' : ''}><span>{connected ? <Check size={14}/> : '2'}</span> AWS 역할 생성</li>
      <li className={connected ? 'done' : ''}><span>{connected ? <Check size={14}/> : '3'}</span> 연결 확인</li>
    </ol>
    <div className="aws-grid"><div className="aws-flow">
      <section className="panel"><h2>{selected ? selected.name : '새 AWS 환경'}</h2>
        {loading && <p role="status"><LoaderCircle size={15} className="spin"/> 연결 정보를 불러오고 있습니다.</p>}
        <form onSubmit={e => { e.preventDefault(); void register(); }}>
          <label htmlFor="aws-name">환경 이름</label><input id="aws-name" value={name} maxLength={100} required placeholder="예: 개인 AWS 테스트" disabled={!available || !ready || !!selected || !!draft} onChange={e => setName(e.target.value)}/>
          <label htmlFor="aws-region">리전</label><select id="aws-region" value={region} required disabled={!available || !ready || !!selected || !!draft} onChange={e => setRegion(e.target.value)}>
            {!supportedRegions.length && <option value="">연결 설정 후 선택할 수 있습니다</option>}
            {supportedRegions.map(value => <option key={value} value={value}>{value === 'ap-northeast-2' ? '서울 · ap-northeast-2' : value}</option>)}
          </select>
          {!selected && <button type="submit" className="primary" disabled={!available || !ready || !name.trim() || !region}>{busy ? <LoaderCircle size={16} className="spin"/> : <Plus size={16}/>} {draft ? '등록 요청 다시 확인' : '등록 시작'}</button>}
        </form>
        {draft && !selected && <p className="helper">이전 등록 요청을 이어서 확인합니다. 같은 요청을 다시 보내도 중복 등록되지 않습니다.</p>}
        {(selected || draft) && <button className="text-link aws-new" disabled={!ready} onClick={startNew}><Plus size={14}/> 새 환경 등록하기</button>}
      </section>
      <section className="panel"><h2>AWS에서 역할 생성</h2>
        {url ? <><p>새 탭에서 본인의 AWS 계정에 로그인한 뒤 IAM 생성에 동의하고 스택을 만드세요.</p><a className="primary" href={url} target="_blank" rel="noopener noreferrer">AWS에서 역할 생성 <ExternalLink size={15}/></a><p className="helper">스택이 CREATE_COMPLETE가 되면 출력(Outputs)의 RoleArn을 복사해 아래에 입력하세요.</p><p className="aws-permission"><ShieldCheck size={15}/> 현재 온보딩 템플릿은 배포 역할에 관리자 권한(AdministratorAccess)을 부여합니다. AWS 화면에서 내용을 확인한 뒤 승인하세요.</p></>
          : <p className="helper">{connected ? 'AWS 역할 연결이 완료됐습니다.' : selected?.status === 'EXPIRED' ? '등록이 만료됐습니다. 새 환경을 등록해 주세요.' : selected?.status === 'VERIFYING' ? '역할을 검증하고 있습니다. 잠시 후 상태를 새로고침하세요.' : '환경 등록 후 역할 생성 링크가 표시됩니다.'}</p>}
      </section>
      <section className="panel"><h2>Role ARN 검증 및 저장</h2><form onSubmit={e => { e.preventDefault(); void verify(); }}>
        <label htmlFor="aws-role-arn">AWS 출력의 RoleArn</label><input id="aws-role-arn" value={roleArn} onChange={e => setRoleArn(e.target.value)} disabled={!canVerify} required autoComplete="off" spellCheck={false} placeholder="arn:aws:iam::123456789012:role/deploy-service-role"/>
        <p className="helper">등록할 때 생성한 External ID로 검증한 뒤 연결 정보를 저장합니다.</p>
        <button className="primary" disabled={!canVerify || !roleArn.trim()} type="submit">{busy ? <LoaderCircle size={16} className="spin"/> : <ShieldCheck size={16}/>} {busy ? '검증하고 있습니다' : '연결 확인'}</button>
      </form></section>
    </div><aside className="aws-summary">
      <section className="panel"><h2>현재 연결 상태</h2><span className={`status aws-status ${connected ? 'is-connected' : ''}`}>{selected ? labels[selected.status] : '미등록'}</span>
        <dl><dt>환경</dt><dd>{selected?.name || '—'}</dd><dt>AWS 계정 ID</dt><dd>{selected?.aws_account_id || '—'}</dd><dt>저장된 Role ARN</dt><dd>{selected?.role_arn || '—'}</dd></dl>
        {selected?.status === 'FAILED' && <p className="helper">권한과 입력한 ARN을 확인한 뒤 같은 환경에서 다시 시도할 수 있습니다.</p>}
        {selected?.status === 'VERIFYING' && <p className="helper">검증 중입니다. 잠시 후 상태 새로고침을 눌러 주세요.</p>}
        {selected?.status === 'EXPIRED' && <p className="helper">24시간이 지나 등록이 만료됐습니다. 새 환경으로 등록해 주세요.</p>}
        {connected && <p className="helper">검증한 연결 정보가 저장돼 있습니다.</p>}
      </section>
      <section className="panel"><h2>등록한 환경</h2>{!rows.length && <p className="helper">{loading ? '불러오는 중…' : '아직 등록한 환경이 없습니다.'}</p>}
        <ul className="aws-environment-list">{rows.map(row => <li key={row.id}><button disabled={!ready} className={selected?.id === row.id ? 'selected' : ''} onClick={() => onSelect(row.id)}><span><Cloud size={15}/>{row.name}</span><small>{labels[row.status]}</small></button></li>)}</ul>
        {hasMore && <button className="text-link aws-new" disabled={!ready} onClick={() => void more()}>더 보기</button>}
      </section>
    </aside></div>
  </div>;
}
