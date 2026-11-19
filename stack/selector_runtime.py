"""Validated v3 runtime boundary for explicit 100 ms twin observation streams.

No KPM-to-neighbour fabrication and no native-RAN CHO configuration. A selected
profile runs in the twin; an optional bridge can request an ordinary OAI HO.
Qualification/gate sidecars are trusted local evidence, not signed certificates.
"""
import hashlib
import copy
import importlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ARCH = 'ctx_cho_selector'
BACKEND_FILES = ('pipeline/twin/selector_v3.py', 'pipeline/twin/cho_v3.py',
                 'pipeline/twin/controllers_v2.py', 'pipeline/twin/sim.py',
                 'pipeline/twin/phy.py', 'pipeline/twin/gate_v3.py',
                 'stack/selector_runtime.py')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def backend_hashes(root):
    return {n: sha256(Path(root) / n) for n in BACKEND_FILES}


def load_backend(root):
    root = Path(root).resolve()
    sys.path.insert(0, str(root / 'pipeline'))
    modules = {}
    for name in ('sim', 'controllers_v2', 'cho_v3', 'selector_v3', 'gate_v3'):
        m = importlib.import_module('twin.' + name)
        if Path(m.__file__).resolve() != (root / 'pipeline/twin' / (name + '.py')).resolve():
            raise ValueError('backend_root_mismatch')
        modules[name] = m
    return modules


def validate_context(context):
    if not isinstance(context, dict):
        raise ValueError('unsupported_input_context')
    if (context.get('format') != 'horus.selector-context/1' or
            context.get('mode') not in ('synthetic-fixture', 'twin-stream') or
            context.get('dt_s') != .1 or type(context.get('l3_k')) is not int or context['l3_k'] != 4 or
            type(context.get('ue_count')) is not int or
            not 1 <= context['ue_count'] <= 128 or
            type(context.get('min_cells')) is not int or type(context.get('max_cells')) is not int or
            not 2 <= context['min_cells'] <= context['max_cells'] <= 256 or
            type(context.get('max_frame_age_s')) not in (int, float) or
            not .1 <= context['max_frame_age_s'] <= 5):
        raise ValueError('unsupported_input_context')
    source = context.get('feature_source')
    if not isinstance(source, dict) or set(source) != {'rsrp', 'sinr', 'network'} or not all(
            isinstance(v, str) and v for v in source.values()):
        raise ValueError('missing_feature_provenance')
    sources = context.get('source_sha256')
    if not isinstance(sources, dict) or not sources or not all(
            isinstance(v, str) and len(v) == 64 and all(c in '0123456789abcdef' for c in v)
            for v in sources.values()):
        raise ValueError('missing_context_source_hashes')
    for key, count in (('cell_ids', None), ('ue_ids', context['ue_count'])):
        ids = context.get(key)
        if (not isinstance(ids, list) or not ids or
                not all(isinstance(x, str) and x for x in ids) or len(set(ids)) != len(ids) or
                (count is not None and len(ids) != count)):
            raise ValueError('missing_qualified_identities')
    canonical_hash(context)


MULTIHEAD_HIDDEN = (16, 1024)


def validate_checkpoint(ck, backend):
    """Two explicit contracts, nothing in between:

    plain (PR #50, v3.39.0): the 16 v3 features, width 64, one utility head, no cost rule.
    multihead (v3.14, finals_preregistration_v3_14.json): a feature set the backend names
      (v3 or trend), any width in MULTIHEAD_HIDDEN, exactly the backend's three prediction
      heads, a backend cost rule with validated parameters and an optional minimum dwell.
    Every other variant (ensembles, input clipping, unknown heads/rules) is refused."""
    if not isinstance(ck, dict) or ck.get('arch') != ARCH:
        raise ValueError('checkpoint_architecture_or_features')
    cho = backend['cho_v3']
    multihead = 'prediction_heads' in ck
    known_sets = [list(v) for v in getattr(cho, 'FEATURE_SETS', {'v3': cho.FEATURE_NAMES}).values()]
    names = list(ck.get('feature_names', []))
    if (names != list(cho.FEATURE_NAMES)) if not multihead else (names not in known_sets):
        raise ValueError('checkpoint_architecture_or_features')
    features = names
    mu, sd = np.asarray(ck['x_mean'], float), np.asarray(ck['x_std'], float)
    if mu.shape != (len(features),) or sd.shape != mu.shape or not np.isfinite([mu, sd]).all() or (sd <= 0).any():
        raise ValueError('checkpoint_normalization')
    profiles = ck['profiles']
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 64:
        raise ValueError('checkpoint_profiles')
    for p in profiles:
        if set(p) != set(backend['cho_v3'].PROFILE_KEYS) or not all(type(p[k]) in (float, int) and math.isfinite(p[k]) for k in p):
            raise ValueError('checkpoint_profile_fields')
        if (not -30 <= p['prep_offset_db'] <= 30 or not -30 <= p['exec_offset_db'] <= 30 or
                not 0 <= p['hys_db'] <= 30 or p['ttt_s'] not in
                (0, .04, .064, .08, .1, .128, .16, .256, .32, .48, .512, .64, 1.024, 1.28, 2.56, 5.12) or
                type(p['l3_k']) is not int or not 0 <= p['l3_k'] <= 19):
            raise ValueError('checkpoint_profile_parameters')
    if type(ck['default']) is not int or not 0 <= ck['default'] < len(profiles):
        raise ValueError('checkpoint_default')
    for key, default in [('period_s', 2), ('warm_s', 10), ('margin', 0), ('switch_margin', 0)]:
        v = ck.get(key, default)
        if type(v) not in (float, int) or not math.isfinite(v) or v < 0 or (key == 'period_s' and v <= 0):
            raise ValueError('checkpoint_decision_constants')
    allowed = np.asarray(ck.get('allowed', [True] * len(profiles)))
    if allowed.shape != (len(profiles),) or allowed.dtype != bool or not allowed[ck['default']]:
        raise ValueError('checkpoint_allowed_profiles')
    if any(k in ck for k in ('x_clip', 'ensemble')):
        raise ValueError('unsupported_selector_variant')
    if not multihead:
        # The plain PR #50 MLP. Cost-head/other variants need the multihead contract
        # below instead of silently ignoring extra semantics.
        if any(k in ck for k in ('cost_rule', 'cost_params', 'head_scales', 'min_dwell_s')) or ck.get('hidden', 64) != 64:
            raise ValueError('unsupported_selector_variant')
        hidden, nout = 64, len(profiles)
    else:
        sel = backend['selector_v3']
        if (not hasattr(sel, 'PREDICTION_HEADS') or list(ck['prediction_heads']) != list(sel.PREDICTION_HEADS) or
                ck.get('cost_rule') not in sel.COST_RULES):
            raise ValueError('unsupported_selector_variant')
        scales = ck.get('head_scales')
        if (not isinstance(scales, list) or len(scales) != len(sel.PREDICTION_HEADS) or
                not all(type(v) in (float, int) and math.isfinite(v) and v > 0 for v in scales)):
            raise ValueError('checkpoint_head_scales')
        try:
            sel.check_cost_params(ck['cost_rule'], ck.get('cost_params'))
        except (ValueError, TypeError, KeyError):
            raise ValueError('checkpoint_cost_params') from None
        dwell = ck.get('min_dwell_s', 0)
        if type(dwell) not in (float, int) or not math.isfinite(dwell) or dwell < 0:
            raise ValueError('checkpoint_decision_constants')
        hidden = ck.get('hidden')
        if type(hidden) is not int or not MULTIHEAD_HIDDEN[0] <= hidden <= MULTIHEAD_HIDDEN[1]:
            raise ValueError('checkpoint_weights')
        nout = len(profiles) * len(sel.PREDICTION_HEADS)
    weights = {k: np.asarray(v.detach().cpu() if hasattr(v, 'detach') else v, float)
               for k, v in ck['state_dict'].items()}
    expected = {}
    for layer, nin, nout in [(0, len(features), hidden), (2, hidden, hidden), (4, hidden, nout)]:
        expected[f'{layer}.weight'], expected[f'{layer}.bias'] = (nout, nin), (nout,)
    if set(weights) != set(expected) or any(weights[k].shape != shape or not np.isfinite(weights[k]).all()
                                           for k, shape in expected.items()):
        raise ValueError('checkpoint_weights')
    return dict(ck, state_dict=weights)


class SelectorRuntime:
    """Artifact reload resets all history. A rejected reload selects A3.

    Invalid frames produce HOLD; a model fault latches A3 until explicit reload
    or a new supported segment. A3 only receives otherwise valid fresh frames.
    """
    def __init__(self, root, context, allow_fixtures=False):
        self.root = Path(root).resolve()
        validate_context(context)
        self.context = copy.deepcopy(context)
        self.context_hash = canonical_hash(context)
        self.backend = load_backend(root)
        self.allow_fixtures = allow_fixtures
        self.version, self.model, self.ck = None, None, None
        self.eligible, self.reason, self.fixture_only = False, 'no_candidate', False
        self.input_qualified = False
        self.bound_files = {}
        self.stats = dict(inference_calls=0, fallback_frames=0, invalid_frames=0, model_faults=0)
        self._last_sequence = None
        self._segment = None
        self._reset_history()

    def _reset_history(self):
        self.baseline = self.backend['controllers_v2'].A3Batch(**self.backend['controllers_v2'].STOCK_A3)
        if self.model is not None:
            self.model.reset()
        self._model_fault = None
        self._last_t = self._last_source_t = None
        self._identities = None

    def load(self, artifact_path):
        """Strict execution eligibility, stronger than metadata-only A1 storage."""
        self.model, self.ck, self.version = None, None, None
        self.eligible, self.fixture_only = False, False
        self.input_qualified = False
        self.bound_files = {}
        self._last_sequence, self._segment = None, None
        self._reset_history()
        try:
            artifact_path = Path(artifact_path).resolve()
            art = read_json(artifact_path)
            from policy_store import _validate_schema
            if _validate_schema(art, self.root / 'schemas/policy_artifact.schema.json'):
                raise ValueError('artifact_schema_invalid')
            self.version = art['version']
            if art['gate']['verdict'] != 'promote':
                raise ValueError('gate_not_promoted')
            if art['algo'] != ARCH:
                raise ValueError('unsupported_artifact_architecture')
            weights = (self.root / art['weights_ref']).resolve()
            if not weights.is_relative_to((self.root / 'pipeline/checkpoints').resolve()) or not weights.is_file():
                raise ValueError('weights_missing_or_outside_checkpoints')
            if weights.name != f"dqn-{self.version}.pt":
                raise ValueError('weights_version_path_mismatch')
            weight_hash, artifact_hash = sha256(weights), canonical_hash(art)
            qualification_path = weights.with_suffix('.qualification.json')
            if not qualification_path.is_file():
                raise ValueError('input_qualification_missing')
            qual = read_json(qualification_path)
            if (qual.get('format') != 'horus.selector-qualification/1' or qual.get('status') != 'qualified' or
                    qual.get('weights_sha256') != weight_hash or qual.get('artifact_canonical_sha256') != artifact_hash or
                    qual.get('context_sha256') != self.context_hash or qual.get('backend_sha256') != backend_hashes(self.root)):
                raise ValueError('input_qualification_mismatch')
            self.fixture_only = qual.get('scope') == 'fixture-only'
            if self.context['mode'] == 'synthetic-fixture':
                if not self.fixture_only or not self.allow_fixtures:
                    raise ValueError('fixture_execution_not_enabled')
            elif self.fixture_only or qual.get('scope') != 'twin-actuation':
                raise ValueError('qualification_scope_mismatch')
            evidence = (self.root / qual['evidence_ref']).resolve()
            if not evidence.is_relative_to(self.root) or sha256(evidence) != qual.get('evidence_sha256'):
                raise ValueError('qualification_evidence_mismatch')
            gate_path = weights.with_suffix('.gate.json')
            gate = read_json(gate_path)
            if gate.get('fixture_only') and not self.fixture_only:
                raise ValueError('fixture_gate_cannot_qualify_actuation')
            cfg_path = self.root / 'pipeline/gate_config_finals.json'
            cfg = read_json(cfg_path)
            if (gate.get('verdict') != 'promote' or gate.get('weights_sha256') != weight_hash or
                    gate.get('artifact_canonical_sha256') != artifact_hash or gate.get('config_sha256') != sha256(cfg_path)):
                raise ValueError('gate_receipt_mismatch')
            rows = gate['rows']
            expected = {(s, f, seed, role) for s in cfg['scenarios'] for f in cfg['fadings']
                        for seed in cfg['seeds'] for role in ('candidate', 'reference')}
            actual = [(r['scenario'], r['fading'], r['seed'], r['role']) for r in rows]
            if len(actual) != len(expected) or set(actual) != expected:
                raise ValueError('gate_receipt_incomplete')
            judge = self.backend['gate_v3']
            for r in rows:
                if (not all(type(r[k]) in (float, int) and math.isfinite(r[k]) and r[k] >= 0
                            for k in ('score', 'mean_se', 'fail_rate', 'pp_rate', 'ho_rate')) or
                        r['score'] != round(judge.episode_score_v3(r, cfg['se_ref']), 4)):
                    raise ValueError('gate_receipt_invalid_score')
            worst, failures = judge.judge(rows, cfg)
            if (failures or art['gate'].get('worst_case_score') != worst['score'] or
                    art['gate'].get('threshold') != cfg['threshold'] or
                    art['gate'].get('scenario_suite') != cfg['scenario_suite']):
                raise ValueError('gate_receipt_guardrails_or_artifact_mismatch')
            import torch
            ck = validate_checkpoint(torch.load(weights, map_location='cpu', weights_only=True), self.backend)
            if ck.get('fixture_only') and not self.fixture_only:
                raise ValueError('fixture_checkpoint_cannot_actuate')
            if ck.get('version') != self.version:
                raise ValueError('checkpoint_version_mismatch')
            self.ck = ck
            self.model = self.backend['selector_v3'].CHOSelectorPolicy(ck)
            predict = self.model.predict

            def checked_predict(x):
                if not np.isfinite(x).all():
                    raise ValueError('nonfinite_features')
                self.stats['inference_calls'] += 1
                q = predict(x)
                allowed = q[:, self.model.allowed]
                if getattr(self.model, 'prediction_heads', None) is not None and self.model.cost_rule != 'utility_only':
                    # multihead contract: a cost rule marks infeasible profiles -inf by design;
                    # NaN, +inf or a non-finite default score is still a model fault
                    if (np.isnan(allowed).any() or np.isposinf(allowed).any() or
                            not np.isfinite(q[:, self.model.default]).all()):
                        raise ValueError('nonfinite_predictions')
                elif not np.isfinite(allowed).all():
                    raise ValueError('nonfinite_predictions')
                return q
            self.model.predict = checked_predict
            self.bound_files = {p: sha256(p) for p in (artifact_path, weights, qualification_path,
                                                       gate_path, cfg_path, evidence)}
            self.bound_files.update({self.root / n: h for n, h in backend_hashes(self.root).items()})
            self.eligible, self.reason = True, 'qualified_fixture' if self.fixture_only else 'qualified_twin_input'
            self.input_qualified = True
        except Exception as exc:
            self.model, self.ck, self.eligible = None, None, False
            self.reason = str(exc) if isinstance(exc, ValueError) else 'invalid_or_missing_policy_bundle'
        return self.status()

    def status(self):
        return dict(candidate_version=self.version, eligible=self.eligible, reason=self.reason,
                    fixture_only=self.fixture_only, context_sha256=self.context_hash,
                    input_qualified=self.input_qualified, input_scope=self.context.get('scope'),
                    runtime_fault=self._model_fault,
                    live_eligible=self.eligible and self.input_qualified and self._model_fault is None and
                                  not self.fixture_only and self.context['mode'] == 'twin-stream',
                    **self.stats)

    def _observation(self, frame, now):
        if frame.get('format') != 'horus.selector-frame/1' or frame.get('context_sha256') != self.context_hash:
            raise ValueError('frame_contract_or_context_mismatch')
        if type(frame['sequence']) is not int or frame['sequence'] < 0 or not isinstance(frame['segment'], str):
            raise ValueError('invalid_sequence_or_segment')
        source = datetime.fromisoformat(frame['source_ts'].replace('Z', '+00:00'))
        if source.tzinfo is None or source.utcoffset().total_seconds() != 0:
            raise ValueError('source_timestamp_must_be_utc')
        age = (now - source).total_seconds()
        if age > self.context['max_frame_age_s'] or age < -.1:
            raise ValueError('stale_or_future_frame')
        t, dt = frame['t_s'], frame['dt_s']
        if type(t) not in (int, float) or not math.isfinite(t) or t < 0 or dt != .1:
            raise ValueError('invalid_observation_clock')
        cells, ues = frame['cell_ids'], frame['ue_ids']
        if (not all(isinstance(v, list) for v in (cells, ues)) or
                not self.context['min_cells'] <= len(cells) <= self.context['max_cells'] or
                len(ues) != self.context['ue_count'] or
                not all(isinstance(x, str) and x for x in cells + ues) or
                len(set(cells)) != len(cells) or len(set(ues)) != len(ues)):
            raise ValueError('invalid_cell_or_ue_identities')
        if not set(cells).issubset(self.context['cell_ids']) or ues != self.context['ue_ids']:
            raise ValueError('unqualified_cell_or_ue_identity')
        n, m = len(ues), len(cells)
        arrays = {}
        shapes = dict(l1=(n, m), l3=(n, m), sinr_db=(n,), time_since_ho=(n,),
                      serving=(n,), connected=(n,), can_ho=(n,), active=(m,))
        for k, shape in shapes.items():
            a = np.asarray(frame[k])
            if a.shape != shape:
                raise ValueError('observation_shape_mismatch')
            if k in ('connected', 'can_ho', 'active'):
                if a.dtype != bool:
                    raise ValueError('observation_boolean_type')
            elif k == 'serving':
                if not np.issubdtype(a.dtype, np.integer) or (a < 0).any() or (a >= m).any():
                    raise ValueError('invalid_serving_index')
            else:
                if a.dtype.kind not in 'iuf':
                    raise ValueError('observation_numeric_type')
                a = a.astype(float)
                if not np.isfinite(a).all():
                    raise ValueError('nonfinite_observation')
            arrays[k] = a
        if (arrays['can_ho'] & ~arrays['connected']).any() or not arrays['active'][arrays['serving']].all():
            raise ValueError('inconsistent_connection_state')
        if (arrays['time_since_ho'] < 0).any():
            raise ValueError('negative_handover_age')
        return self.backend['sim'].Obs(t=t, dt=dt, cell_ids=cells, ue_ids=ues, **arrays), source.timestamp()

    def step(self, frame, now=None):
        now = now or datetime.now(timezone.utc)
        try:
            obs, source_t = self._observation(frame, now)
            changed = frame['segment'] != self._segment
            if self._last_sequence is not None and frame['sequence'] != self._last_sequence + 1:
                raise ValueError('noncontiguous_sequence')
            if changed:
                self._reset_history()
                self._segment = frame['segment']
                if abs(obs.t-.1)>1e-6:
                    self._model_fault = 'segment_started_without_initial_state'
            identities = (tuple(obs.cell_ids), tuple(obs.ue_ids))
            if self._identities is not None and identities != self._identities:
                raise ValueError('identities_changed_without_segment_reset')
            if self._last_t is not None and (abs(obs.t - self._last_t - .1) > 1e-6 or
                                             abs(source_t - self._last_source_t - .1) > 1e-4):
                raise ValueError('noncontiguous_observation_clock')
            self._identities = identities
            self._last_sequence, self._last_t, self._last_source_t = frame['sequence'], obs.t, source_t
        except Exception as exc:
            self.stats['invalid_frames'] += 1
            self.baseline.reset()
            self._model_fault = 'input_continuity_lost'
            # Establish only a new continuity anchor after a readable gap. This
            # frame still produces HOLD; subsequent valid frames can run A3.
            if isinstance(frame, dict) and type(frame.get('sequence')) is int and frame['sequence'] >= 0:
                if self._last_sequence is None or frame['sequence'] > self._last_sequence:
                    self._last_sequence = frame['sequence']
                    self._last_t = self._last_source_t = None
            return dict(effective_controller='hold', reason=str(exc) if isinstance(exc, ValueError) else 'invalid_frame',
                        candidate_version=self.version, targets=[], selected_profiles=[], native_cho_configured=False,
                        context_sha256=self.context_hash, live_eligible=False, fixture_only=self.fixture_only)
        if self.eligible and self._model_fault is None:
            try:
                try:
                    unchanged = all(sha256(p) == h for p, h in self.bound_files.items())
                except OSError:
                    unchanged = False
                if not unchanged:
                    self.input_qualified = False
                    raise ValueError('policy_bundle_changed')
                targets, conditional = self.model.decide_batch(obs)
                if (targets.shape != obs.serving.shape or not np.issubdtype(targets.dtype, np.integer) or
                        (targets < -1).any() or (targets >= len(obs.cell_ids)).any() or
                        ((targets >= 0) & (~obs.can_ho | (targets == obs.serving))).any() or
                        ((targets >= 0) & ~obs.active[np.maximum(targets, 0)]).any() or
                        (conditional is not None and (conditional.shape != targets.shape or conditional.dtype != bool))):
                    raise ValueError('invalid_policy_target')
                chosen = self.model.engine.current
                profiles = [dict(index=int(p), parameters=dict(self.ck['profiles'][int(p)])) for p in chosen]
                effective, reason = 'selector', self.reason
            except Exception as exc:
                self._model_fault = str(exc) if isinstance(exc, ValueError) else 'model_execution_failed'
                self.stats['model_faults'] += 1
                self.baseline.reset()
        if not self.eligible or self._model_fault is not None:
            targets, conditional = self.baseline.decide_batch(obs)
            profiles, effective = [], 'a3'
            reason = self._model_fault or self.reason
            self.stats['fallback_frames'] += 1
        return dict(candidate_version=self.version, effective_controller=effective, reason=reason,
                    context_sha256=self.context_hash, t_s=obs.t, sequence=frame['sequence'], segment=frame['segment'],
                    source_ts=frame['source_ts'], input_age_s=now.timestamp()-source_t,
                    ue_ids=obs.ue_ids, from_cells=[obs.cell_ids[i] for i in obs.serving],
                    targets=[None if i < 0 else obs.cell_ids[int(i)] for i in targets],
                    selected_profiles=profiles,
                    conditional_in_twin=[False] * len(targets) if conditional is None else conditional.tolist(),
                    rsrp_serving=[float(obs.l1[u, s]) for u, s in enumerate(obs.serving)],
                    rsrp_target=[None if s < 0 else float(obs.l1[u, s]) for u, s in enumerate(targets)],
                    native_cho_configured=False, fixture_only=self.fixture_only,
                    selector_stage=('warm_default' if self.model is not None and
                                    obs.t-self.model._t0+1e-9 < self.model.warm_s else 'learned_profiles') if effective=='selector' else None,
                    live_eligible=self.status()['live_eligible'] and effective == 'selector',
                    control_eligible=self.input_qualified and not self.fixture_only and self.context['mode']=='twin-stream')


def frame_from_observation(obs, context, sequence, segment, source_ts):
    """Producer helper: no interpolation, synthetic neighbours or unit offsets."""
    return dict(format='horus.selector-frame/1', context_sha256=canonical_hash(context), sequence=sequence,
                segment=segment, source_ts=source_ts, t_s=obs.t, dt_s=obs.dt,
                cell_ids=list(obs.cell_ids), ue_ids=list(obs.ue_ids),
                **{k: np.asarray(getattr(obs, k)).tolist() for k in
                   ('l1', 'l3', 'serving', 'sinr_db', 'connected', 'can_ho', 'time_since_ho', 'active')})
