"""Compile a building structure JSON to a fresh reference directory, without AI.

Example: .local/python/bin/python3 pipeline/build_building_reference.py \
    --spec examples/buildings/cottage.json --output .local/building-reference/cottage-v2
"""
import argparse
import json
from pathlib import Path

from building_structure import compile_structure


def build(output, spec=None):
    return compile_structure(spec or {}, output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, help='Building structure JSON; omit for a 3x2 gable house')
    parser.add_argument('--output', type=Path, required=True, help='New output directory; never overwrites')
    args = parser.parse_args()
    build(args.output, json.loads(args.spec.read_text()) if args.spec else {})
    print(args.output.resolve())
