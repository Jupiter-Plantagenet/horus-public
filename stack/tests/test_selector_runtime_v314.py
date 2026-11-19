"""The v3.14 multihead runtime contract (stack/selector_runtime.validate_checkpoint):
accepted exactly as specified, every deviation refused, the plain v3.39.0 contract unchanged,
and the runtime makes the same decisions as the backend selector. No Docker or RAN access."""
import copy
from datetime import datetime
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import numpy as np

STACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STACK))
from selector_runtime import SelectorRuntime, load_backend, validate_checkpoint
from selector_fixtures import make_fixture, frames


def now(frame):
    return datetime.fromisoformat(frame['source_ts'].replace('Z', '+00:00'))


class MultiheadContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(os.environ.get('HORUS_SELECTOR_ROOT', STACK.parent)).resolve()
        cls.temp = tempfile.TemporaryDirectory(prefix='horus-selector-v314-tests-')
        cls.root = Path(cls.temp.name).resolve()/'assembly'
        cls.root.mkdir()
        for name in ('pipeline', 'schemas'):
            shutil.copytree(source/name, cls.root/name, ignore=shutil.ignore_patterns('__pycache__', 'env', '.env'))
        (cls.root/'stack').mkdir()
        (cls.root/'stack/selector_runtime.py').write_bytes((STACK/'selector_runtime.py').read_bytes())
        cls.backend = load_backend(cls.root)
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fixture(self, multihead=True):
        type(self).n += 1
        return make_fixture(self.root, f'v0.14.{self.n}', multihead=multihead)

    def test_multihead_fixture_loads_and_matches_the_backend_selector_frame_by_frame(self):
        fx = self.fixture()
        rt = SelectorRuntime(self.root, fx['context'], allow_fixtures=True)
        st = rt.load(fx['artifact'])
        self.assertTrue(st['eligible'], st['reason'])
        ref = self.backend['selector_v3'].CHOSelectorPolicy(validate_checkpoint(copy.deepcopy(fx['checkpoint']), self.backend))
        chose_learned = False
        for fr in frames(fx):
            d = rt.step(fr, now=now(fr))
            obs, _ = rt._observation(fr, now(fr))
            rt_targets, _ = ref.decide_batch(obs)
            self.assertEqual(d['effective_controller'], 'selector')
            self.assertEqual([p['index'] for p in d['selected_profiles']], ref.engine.current.tolist())
            self.assertEqual(d['targets'], [None if t < 0 else fr['cell_ids'][t] for t in rt_targets])
            chose_learned |= ref.engine.current.tolist() == [1]
        self.assertTrue(chose_learned)            # profile 1 is inside the 0.3 HO budget and is chosen
        self.assertEqual(rt.status()['model_faults'] + rt.status()['fallback_frames'] + rt.status()['invalid_frames'], 0)

    def _bias(self, fx, bias):
        import torch
        sd = dict(fx['checkpoint']['state_dict'])
        sd['4.bias'] = torch.tensor(bias)
        return sd

    def test_infeasible_profile_is_not_a_fault_but_nan_is(self):
        fx = self.fixture()
        rt = SelectorRuntime(self.root, fx['context'], allow_fixtures=True)
        self.assertTrue(rt.load(fx['artifact'])['eligible'])
        # profile 1 predicts HO 2.0 against the default's 1.0: outside the 0.3 budget -> -inf, default kept
        rt.model.net.b[2][:] = [0., 1.0, 0.5, 1.0, 2.0, 0.5]
        for fr in frames(fx):
            d = rt.step(fr, now=now(fr))
            self.assertEqual(d['effective_controller'], 'selector', d['reason'])
            self.assertEqual([p['index'] for p in d['selected_profiles']], [0])
        self.assertEqual(rt.status()['model_faults'], 0)
        self.assertGreater(rt.model.cost_blocked, 0)
        fx2 = self.fixture()
        rt2 = SelectorRuntime(self.root, fx2['context'], allow_fixtures=True)
        self.assertTrue(rt2.load(fx2['artifact'])['eligible'])
        rt2.model.net.b[2][:] = [0., 1.0, 0.5, float('nan'), 1.2, 0.5]
        out = [rt2.step(fr, now=now(fr)) for fr in frames(fx2)]
        self.assertEqual(rt2.status()['runtime_fault'], 'nonfinite_cost_predictions')
        self.assertEqual(out[-1]['effective_controller'], 'a3')

    def _refused(self, change, reason):
        fx = self.fixture()
        ck = copy.deepcopy(fx['checkpoint'])
        change(ck)
        with self.assertRaises(ValueError) as cm:
            validate_checkpoint(ck, self.backend)
        self.assertEqual(str(cm.exception), reason)

    def test_every_deviation_from_the_multihead_contract_is_refused(self):
        self._refused(lambda c: c.update(prediction_heads=['utility_delta']), 'unsupported_selector_variant')
        self._refused(lambda c: c.update(cost_rule='sometimes'), 'unsupported_selector_variant')
        self._refused(lambda c: c.update(cost_params=dict(ho_penalty=-1., fail_penalty=0., ho_slack=0.3, fail_slack=None)),
                      'checkpoint_cost_params')
        self._refused(lambda c: c.update(cost_params=None), 'checkpoint_cost_params')
        self._refused(lambda c: c.update(head_scales=[1., 1.]), 'checkpoint_head_scales')
        self._refused(lambda c: c.update(head_scales=[1., 0., 5.]), 'checkpoint_head_scales')
        self._refused(lambda c: c.update(min_dwell_s=-1.), 'checkpoint_decision_constants')
        self._refused(lambda c: c.update(hidden=33), 'checkpoint_weights')        # declared width != tensors
        self._refused(lambda c: c.update(hidden=8), 'checkpoint_weights')
        self._refused(lambda c: c.update(ensemble=[]), 'unsupported_selector_variant')
        self._refused(lambda c: c.update(x_clip=3.), 'unsupported_selector_variant')
        self._refused(lambda c: c.update(feature_names=c['feature_names'][:-1]), 'checkpoint_architecture_or_features')

    def test_plain_contract_is_unchanged(self):
        fx = self.fixture(multihead=False)
        ck = fx['checkpoint']
        validate_checkpoint(copy.deepcopy(ck), self.backend)
        for extra in (dict(cost_rule='utility_only'), dict(cost_params=None), dict(min_dwell_s=0.),
                      dict(head_scales=[1., 1., 5.]), dict(hidden=128)):
            with self.assertRaises(ValueError) as cm:
                validate_checkpoint(dict(copy.deepcopy(ck), **extra), self.backend)
            self.assertEqual(str(cm.exception), 'unsupported_selector_variant')
        trend = list(self.backend['cho_v3'].FEATURE_NAMES_TREND)
        with self.assertRaises(ValueError) as cm:            # trend features need the multihead contract
            validate_checkpoint(dict(copy.deepcopy(ck), feature_names=trend), self.backend)
        self.assertEqual(str(cm.exception), 'checkpoint_architecture_or_features')


if __name__ == '__main__':
    unittest.main()
