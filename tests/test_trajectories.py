import unittest,tempfile,json
from pathlib import Path
from expressive_arm.trajectory import catalog,load,pose,crop,validate_rows,plot,JOINTS,export_csv

class DataTests(unittest.TestCase):
    def test_all_confirmed_motions_have_valid_manifests(self):
        self.assertEqual(len(catalog()['expressions']),8)
        for e in catalog()['expressions']:
            rows=load(e['id']);self.assertEqual(rows[0]['t'],0)
            self.assertTrue(e['confirmed']);self.assertEqual(set(rows[0]['action']),set(JOINTS))
    def test_rejects_nonfinite_and_wrong_units(self):
        p=dict(load('curious')[0]['action'])
        for value in (101,-1,float('nan'),True):
            bad={**p,'gripper.pos':value}
            with self.assertRaises(ValueError):pose(bad)
        with self.assertRaises(ValueError):pose({'pan':0})
    def test_rejects_duplicate_and_reversed_times(self):
        a,b=load('sleepy')[:2]
        for t in (a['t'],a['t']-1,float('nan')):
            with self.assertRaises(ValueError):validate_rows([a,{**b,'t':t}])
    def test_crop_preserves_targets_and_rebases_without_mutation(self):
        rows=load('happy');part=crop(rows,2,5)
        original=[r for r in rows if 2<=r['t']<=5]
        self.assertEqual(part[0]['t'],0);self.assertEqual(part[-1]['action'],original[-1]['action'])
        self.assertEqual(part[-1]['t'],original[-1]['t']-original[0]['t'])
        self.assertGreater(original[0]['t'],0)
        with self.assertRaises(ValueError):crop(rows,0,1000)
    def test_csv_preserves_every_time_and_target_without_observed_columns(self):
        import csv
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'nested'/'happy.csv'
            export_csv('happy', p)
            with p.open(newline='') as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, ['t', *JOINTS])
                exported = list(reader)
            original = load('happy')
            self.assertEqual(len(exported), len(original))
            for expected, actual in zip(original, exported):
                self.assertEqual(float(actual['t']), expected['t'])
                self.assertEqual({key: float(actual[key]) for key in JOINTS}, expected['action'])

    def test_csv_unknown_expression_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'bad.csv'
            with self.assertRaises(ValueError):
                export_csv('not-a-clip', p)
            self.assertFalse(p.exists())

    def test_plot_is_parseable_and_contains_six_channels(self):
        import xml.etree.ElementTree as E
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'plot.svg';plot('hesitant',p);root=E.parse(p).getroot()
            self.assertEqual(len(root.findall('{http://www.w3.org/2000/svg}polyline')),6)

if __name__=='__main__':unittest.main()
