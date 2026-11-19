// Bilingual labels. Key network terms stay bilingual in both languages.
const S = {
  en: {
    title: 'Campus Twin', subtitle: 'Kumoh National Institute of Technology · 금오공과대학교',
    provenance: 'Provenance', now: 'Now', decision: 'AI decision', ran: 'RAN execution', artifact: 'Active artifact',
    acceptance: 'Execution evidence', service: 'Service observations',
    serving: 'Serving', target: 'Target', none: 'none', sinr: 'SINR', step: 'Step', profile: 'CHO profile',
    stage: 'Stage', prep: 'Prep offset', exec: 'Exec offset', hys: 'Hysteresis', ttt: 'TTT',
    st_decision: 'Decide', st_sent: 'Send', st_ack: 'RIC ACK', st_cu: 'CU RRC',
    ran_idle: 'No control in flight', ran_last: 'Last handover', du: 'DU',
    scen_v314: 'HORUS v3.14 (modelled)', scen_seg0v314: 'Executed · v3.14.24', scen_seg0: 'Executed · v3.39.0 (finals)', scen_walk: 'Full campus walk', scen_sample: 'Sample', scen_live: 'Live', scen_console: 'Console scene',
    view_hero: 'Hero', view_follow: 'Follow', view_overview: 'Campus', view_top: 'Top', view_free: 'Free',
    mode_live: 'LIVE', mode_replay: 'REPLAY', mode_sample: 'SAMPLE', mode_stale: 'LIVE · STALE', mode_waiting: 'LIVE · WAITING',
    sample_bar: 'SAMPLE DATA — synthetic, exercises the interface, not a result',
    waiting_t: 'Waiting for live frames', waiting_d: 'No session frames yet. Start the release runner, or press R for the recorded replay.',
    stale_d: 'Live input is stale', stale_note: 'Showing the last received state. Service status is unknown until fresh input resumes.', lane_horus: 'HORUS', lane_base: 'Baseline', lane_net: 'Network', lane_cells: 'Serving cell', lane_rtt: 'RTT',
    pending: 'pending', not_captured: 'not captured', cycles: 'cycles', confirmed: 'CU-confirmed', two_hour: '2-hour run',
    dec_cu: 'Decision → CU p50', ack: 'RIC ACK p50', faults: 'model faults / fallback', cycle: 'Cycle',
    rtt_p50: 'RTT p50', rtt_p95: 'RTT p95', replies_after: 'Probe replies after each CU ✓', probes: 'ICMP probes · 1 s · emulated RF',
    artifact_central: 'central', artifact_fed: 'federated', fed_pending: 'Federated artifact', gate: 'Operator gate', status_np: 'not provided',
    ho: 'Handover', obs_change: 'Network cell change', modelled: 'modelled', observed: 'observed', confirmed_s: 'confirmed',
    venue: 'Finals venue', strongest: 'strongest measured point · mast unknown',
    walk_note: 'Recorded LG U+ serving cells along the Oct 2026 walk', cmp_title: 'Modelled HO count by segment', cmp_horus: 'HORUS v3.39.0', cmp_a3: 'Stock A3', cmp_cho: 'Network CHO', cmp_mro: 'MRO CHO',
    paused: 'paused', copy_ok: 'Link copied',
  },
  ko: {
    title: '캠퍼스 디지털 트윈', subtitle: '금오공과대학교 · Kumoh National Institute of Technology',
    provenance: '데이터 출처', now: '현재', decision: 'AI 결정', ran: 'RAN 실행', artifact: '활성 모델',
    acceptance: '실행 증거', service: '서비스 관측',
    serving: '서빙 셀', target: '타깃 셀', none: '없음', sinr: 'SINR', step: '스텝', profile: 'CHO 프로파일',
    stage: '단계', prep: '준비 오프셋', exec: '실행 오프셋', hys: '히스테리시스', ttt: 'TTT',
    st_decision: '결정', st_sent: '전송', st_ack: 'RIC ACK', st_cu: 'CU RRC',
    ran_idle: '진행 중인 제어 없음', ran_last: '최근 핸드오버', du: 'DU',
    scen_v314: 'HORUS v3.14 (모델)', scen_seg0v314: '실행 · v3.14.24', scen_seg0: '실행 · v3.39.0 (결선)', scen_walk: '캠퍼스 전체 보행', scen_sample: '샘플', scen_live: '실시간', scen_console: '콘솔 장면',
    view_hero: '메인', view_follow: '추적', view_overview: '캠퍼스', view_top: '평면', view_free: '자유',
    mode_live: '실시간', mode_replay: '녹화 재생', mode_sample: '샘플', mode_stale: '실시간 · 지연', mode_waiting: '실시간 · 대기',
    sample_bar: '샘플 데이터 — 인터페이스 시연용 합성 데이터이며 결과가 아님',
    waiting_t: '실시간 프레임 대기 중', waiting_d: '세션 프레임이 아직 없습니다. 릴리스 러너를 시작하거나 R 키로 녹화 재생을 여세요.',
    stale_d: '실시간 입력 지연', stale_note: '마지막 수신 상태를 표시합니다. 새 입력이 도착할 때까지 서비스 상태는 미확인입니다.', lane_horus: 'HORUS', lane_base: '기준', lane_net: '네트워크', lane_cells: '서빙 셀', lane_rtt: 'RTT',
    pending: '대기', not_captured: '미수집', cycles: '사이클', confirmed: 'CU 확인', two_hour: '2시간 실행',
    dec_cu: '결정 → CU p50', ack: 'RIC ACK p50', faults: '모델 오류 / 폴백', cycle: '사이클',
    rtt_p50: 'RTT p50', rtt_p95: 'RTT p95', replies_after: 'CU 확인 후 프로브 응답', probes: 'ICMP 프로브 · 1초 · 에뮬레이션 RF',
    artifact_central: '중앙 학습', artifact_fed: '연합 학습', fed_pending: '연합 학습 모델', gate: '운영 게이트', status_np: '미제공',
    ho: '핸드오버', obs_change: '네트워크 셀 변경', modelled: '모델링', observed: '관측', confirmed_s: '확인됨',
    venue: '결선 장소', strongest: '최강 측정 지점 · 기지국 위치 미상',
    walk_note: '10월 보행 중 LG U+ 실제 서빙 셀', cmp_title: '구간별 핸드오버 수 (모델링)', cmp_horus: 'HORUS v3.39.0', cmp_a3: '기본 A3', cmp_cho: '네트워크 CHO', cmp_mro: 'MRO CHO',
    paused: '일시정지', copy_ok: '링크 복사됨',
  },
};
let lang = 'en';
export const setLang = (l) => { lang = S[l] ? l : 'en'; document.documentElement.lang = lang; };
export const getLang = () => lang;
export const t = (k) => (S[lang][k] ?? S.en[k] ?? k);
export const tk = (k) => S.ko[k] ?? k;
export function applyStatic(root = document) {
  root.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll('[data-i18n-ko]').forEach((el) => {
    // The secondary label shows the *other* language, keeping key terms bilingual.
    el.textContent = lang === 'en' ? S.ko[el.dataset.i18nKo] : S.en[el.dataset.i18nKo];
  });
}
