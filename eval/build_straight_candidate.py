"""Freeze one simulator-only experiment from the verified no-bounce pilot."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flightops.freeze import freeze, verify

PARENT = 'p2_overflight_no_bounce'
# v2: the first build (p2_straight_recovery) put straight_pitch_floor=0.35 in
# DEFAULTS, where forward_pitch defaults to 0.07, so GateGuidance() raised
# "Invalid straight approach pitch floor". Frozen versions are never edited,
# so the fixed candidate gets a new name.
NAME = 'p2_straight_recovery_v2'

def main():
    assert not verify(PARENT), 'Parent has changed'
    source = ROOT / 'versions' / PARENT
    manifest = json.loads((source / 'version.json').read_text())
    with tempfile.TemporaryDirectory(prefix='roadtrip-straight-') as temp:
        stage = Path(temp)
        for rel in manifest['files']:
            dest = stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / rel, dest)
        path = stage / 'pilot/guidance.py'
        text = path.read_text(encoding='utf-8')
        anchor = '    "ground_pitch": 0.12,'
        assert text.count(anchor) == 1
        # Default 0.0 (off): GateGuidance() with DEFAULTS must stay valid at the
        # default forward_pitch of 0.07. This candidate's config enables 0.35.
        text = text.replace(anchor, '    "straight_pitch_floor": 0.0,  # keep moving on aligned approaches despite noisy altitude settling (config enables it)\n' + anchor)
        anchor = '        self.future = []'
        assert text.count(anchor) == 1
        text = text.replace(anchor, '        if not 0 <= c["straight_pitch_floor"] <= c["forward_pitch"]:\n            raise ValueError("Invalid straight approach pitch floor")\n' + anchor)
        anchor = '        if c["vert_brake"] and near and ey > c["alignment_y"]:'
        assert text.count(anchor) == 1
        block = '''        # In the simulator, noisy vertical-speed estimates can repeatedly stop
        # an otherwise aligned approach. Keep modest forward motion while the
        # visible gate remains ahead and within the vertical alignment band.
        # Turns, large vertical errors, recover/search states and the existing
        # post-contact pitch cap retain their original behavior.
        if (not c["near_brake"] and abs(self.x) < c["alignment_x"]*0.5
                and abs(ey) < c["alignment_y"]):
            pitch = max(pitch, c["straight_pitch_floor"])
'''
        text = text.replace(anchor, block + anchor)
        path.write_text(text, encoding='utf-8')
        config_path = stage / 'config.json'
        config = json.loads(config_path.read_text())
        config['gate_pilot']['straight_pitch_floor'] = 0.35
        config_path.write_text(json.dumps(config, indent=2) + '\n')
        pending = (ROOT / 'versions' / f'.{NAME}.tmp').resolve()
        assert pending.parent == (ROOT / 'versions').resolve()
        meta = freeze(NAME, stage,
                      overrides=['gate_pilot.straight_pitch_floor=0.35'],
                      desc='Simulator aligned-approach pitch floor to reduce altitude-settling stop/start; cruise 0.7 and recovery retained',
                      parent=PARENT, source_label='eval/build_straight_candidate.py from verified parent')
        assert not verify(NAME), 'New candidate failed verification'
        print(meta['name'], meta['tree_sha256'])

if __name__ == '__main__':
    main()
