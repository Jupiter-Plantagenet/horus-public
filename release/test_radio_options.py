"""A radio override cannot be inherited or half-selected by a release command."""
from pathlib import Path
import argparse
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import run_demo
import spooled_demo


class RadioOptions(unittest.TestCase):
    def test_unselected_radio_overrides_cannot_leak_from_the_parent(self):
        poisoned={'HORUS_NR_UE_IMAGE':'foreign/ue:tag','HORUS_CU_IMAGE':'foreign/cu:tag',
                  'HORUS_DU_IMAGE':'foreign/du:tag',
                  'HORUS_FLEXRIC_IMAGE':'foreign/ric:tag',
                  'HORUS_LAB_SRB_REORDERING_MS':'0','COMPOSE_FILE':'foreign-compose.yaml','COMPOSE_ENV_FILES':'foreign-env'}
        with patch.dict(run_demo.os.environ,poisoned):
            env=run_demo.radio_environment(Path('owned-profile'),SimpleNamespace())
        self.assertFalse(any(k.startswith('HORUS_') for k in poisoned if k in env))
        self.assertEqual(env['COMPOSE_FILE'],str(Path('owned-profile/docker-compose.yml')))
        self.assertEqual(env['COMPOSE_ENV_FILES'],'/dev/null')

    def test_explicit_cu_selection_keeps_the_stock_ue(self):
        env=run_demo.radio_environment(Path('owned-profile'),SimpleNamespace(
            cu_image='horus/oai-gnb:srb-reorder-diagnostic',cu_srb_reordering_ms=1000))
        self.assertEqual(env['HORUS_CU_IMAGE'],'horus/oai-gnb:srb-reorder-diagnostic')
        self.assertEqual(env['HORUS_LAB_SRB_REORDERING_MS'],'1000')
        self.assertNotIn('HORUS_NR_UE_IMAGE',env)

    def test_crash_cleanup_keeps_owned_compose_and_clears_inherited_radio(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);capture=root/'capture';capture.mkdir()
            (capture/'startup.txt').write_text('owned startup attempted')
            profile=(root/'stack/oai-ho').resolve()
            with patch.dict(run_demo.os.environ,{'COMPOSE_FILE':'foreign.yaml','HORUS_CU_IMAGE':'bad image'}), \
                 patch.object(spooled_demo.subprocess,'check_output',side_effect=['ho-cu\n',str(profile)+'\n']), \
                 patch.object(spooled_demo.subprocess,'run') as command:
                self.assertTrue(spooled_demo.cleanup_owned(root,capture))
            env=command.call_args.kwargs['env']
            self.assertEqual(env['COMPOSE_FILE'],str(profile/'docker-compose.yml'))
            self.assertNotIn('HORUS_CU_IMAGE',env)

    def test_explicit_du_selection_does_not_select_other_images(self):
        env=run_demo.radio_environment(Path('owned-profile'),SimpleNamespace(du_image='horus/oai-gnb:cfra-retry-diagnostic'))
        self.assertEqual(env['HORUS_DU_IMAGE'],'horus/oai-gnb:cfra-retry-diagnostic')
        self.assertNotIn('HORUS_NR_UE_IMAGE',env)
        self.assertNotIn('HORUS_CU_IMAGE',env)
        self.assertNotIn('HORUS_LAB_SRB_REORDERING_MS',env)

    def test_invalid_du_reference_refuses_before_output(self):
        for runner in (run_demo.run,spooled_demo.run):
            with tempfile.TemporaryDirectory() as temp:
                out=Path(temp)/'untouched'
                with self.assertRaises(argparse.ArgumentTypeError):
                    runner(SimpleNamespace(root=Path(temp),out=out,live=True,du_image='bad image'))
                self.assertFalse(out.exists())

    def test_explicit_ric_selection_does_not_select_other_images(self):
        env=run_demo.radio_environment(Path('owned-profile'),SimpleNamespace(flexric_image='horus/oai-flexric:reply-order-diagnostic'))
        self.assertEqual(env['HORUS_FLEXRIC_IMAGE'],'horus/oai-flexric:reply-order-diagnostic')
        self.assertNotIn('HORUS_NR_UE_IMAGE',env)
        self.assertNotIn('HORUS_CU_IMAGE',env)
        self.assertNotIn('HORUS_DU_IMAGE',env)

    def test_invalid_ric_reference_refuses_before_output(self):
        for runner in (run_demo.run,spooled_demo.run):
            with tempfile.TemporaryDirectory() as temp:
                out=Path(temp)/'untouched'
                with self.assertRaises(argparse.ArgumentTypeError):
                    runner(SimpleNamespace(root=Path(temp),out=out,live=True,flexric_image='bad image'))
                self.assertFalse(out.exists())

    def test_default_and_explicit_pair_are_valid(self):
        for options in ({},{'cu_image':'horus/oai-gnb:srb-reorder-diagnostic','cu_srb_reordering_ms':1000}):
            run_demo.validate_radio_options(SimpleNamespace(**options))

    def test_partial_selection_or_wrong_timer_refuses_before_any_output(self):
        for options in ({'cu_image':'horus/oai-gnb:test'}, {'cu_srb_reordering_ms':1000},
                        {'cu_image':'horus/oai-gnb:test','cu_srb_reordering_ms':0},
                        {'cu_image':'horus/oai-gnb:test','cu_srb_reordering_ms':True}):
            for runner in (run_demo.run,spooled_demo.run):
                with tempfile.TemporaryDirectory() as temp:
                    out=Path(temp)/'preserved'
                    args=SimpleNamespace(root=Path(temp),out=out,live=True,**options)
                    with self.subTest(options=options,runner=runner.__module__),self.assertRaises(ValueError):
                        runner(args)
                    self.assertFalse(out.exists())

    def test_invalid_image_reference_refuses(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            run_demo.validate_radio_options(SimpleNamespace(cu_image='bad image',cu_srb_reordering_ms=1000))


if __name__=='__main__':unittest.main()
