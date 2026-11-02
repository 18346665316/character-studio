"""Copy a verified building candidate into the isolated Godot acceptance scene.

No generation or publication. Calibration is a game-side experiment, not a
change to the source task or a claim of production readiness.
"""
import argparse
from pathlib import Path
import shutil

from asset_repository import atomic
import building_pipeline as bp
from building_candidates import verify_evidence

ROOT = Path(__file__).resolve().parent.parent


def assemble(task, attempt=None):
    folder, job = bp.require_job(ROOT, task)
    if job.get('workflow') != 'line_drawing' or job.get('purpose') == 'template':
        raise ValueError('请选择建筑外观任务')
    attempt = attempt or job['current_attempt']
    if attempt not in job['attempts']:
        raise ValueError('候选不存在')
    target = bp.attempt_folder(folder, attempt)
    bp.verify_inputs(folder, job); bp.verify_attempt(folder, target, job)
    verify_evidence(folder, target)
    if task != '20261102-153942-af274361' or attempt != '20261102-153942-a99c4e06':
        raise ValueError('此候选尚无测试标定；请为实际建筑填写独立标定')
    assets = ROOT/'demo/isometric/assets'
    (assets/'textures').mkdir(parents=True, exist_ok=True)
    shutil.copyfile(target/'sprite.png', assets/'textures/building.png')
    shutil.copytree(ROOT/'demo/yard/assets/character_assets', assets/'character_assets', dirs_exist_ok=True)
    # Explicit manual pixel measurements for this candidate only. Never silently
    # reuse them on another shape or infer them from the image canvas size.
    record = dict(task=task, attempt=attempt, raw_sha256=bp.digest(target/'raw.png'),
                  sprite_sha256=bp.digest(target/'sprite.png'),
                  anchor_px=[526,636], entrance_px=[603,681],
                  footprint_px=[[266,694],[396,781],[786,579],[656,492]],
                  scale=.75, calibration='manual_demo_estimate_not_published',
                  character_view='three_quarter_not_validated_for_isometric',
                  new_ai_calls=0, production_ready=False)
    atomic(assets/'building.json', record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', default='20261102-153942-af274361')
    parser.add_argument('--attempt')
    args = parser.parse_args()
    print(assemble(args.task, args.attempt))
