"""Validate immutable terrain deliveries and their downloadable archive together."""
import hashlib
import json
from pathlib import Path
import zipfile
import zlib

from asset_repository import AssetRepository, read


def inspect(root, subtree, identity):
    assets=AssetRepository(root)
    prefix=f'{subtree}/{identity}'
    errors=[]
    try:
        folder=assets.scoped(prefix,subtree)
        manifest_path=assets.scoped(prefix+'/manifest.json',prefix)
        manifest=read(manifest_path)
        if not isinstance(manifest,dict): raise ValueError('清单缺失或损坏')
        required={'preview.png','atlas.png','INTEGRATION.md'}
        if subtree=='terrain-kits':
            required.update({'ground_material.png',manifest['ground']})
            if manifest.get('asset_type')!='material': required.add('road_material.png')
            groups=manifest.get('variants') or [{'tiles':manifest['tiles'],'ground':manifest['ground']}]
            for group in groups:
                required.add(group['ground'])
                for tile in group['tiles']: required.update((tile['image'],tile['overlay']))
        else:
            required.update(tile['image'] for tile in manifest['tiles'])
        expected=dict(manifest.get('files_sha256',{}))
        if subtree=='terrain-kits':
            expected.update({'inputs/'+p:sha for p,sha in manifest.get('source_sha256',{}).items()})
        for relative in required|set(expected):
            path=assets.scoped(prefix+'/'+relative,prefix)
            if not path.is_file(): raise ValueError('文件缺失：'+relative)
            if relative in expected and hashlib.sha256(path.read_bytes()).hexdigest()!=expected[relative]:
                raise ValueError('文件指纹不一致：'+relative)
        archive_path=assets.scoped(prefix+'/kit.zip',prefix)
        with zipfile.ZipFile(archive_path) as archive:
            names=archive.namelist()
            if len(names)!=len(set(names)): raise ValueError('ZIP 包含重复文件')
            if not (required|set(expected)|{'manifest.json'}).issubset(names):
                raise ValueError('ZIP 缺少交付文件')
            for relative in names:
                if Path(relative).is_absolute() or '..' in Path(relative).parts:
                    raise ValueError('ZIP 文件路径无效')
                path=assets.scoped(prefix+'/'+relative,prefix)
                content=archive.read(relative) # also validates CRC
                if relative=='manifest.json':
                    if json.loads(content)!=manifest: raise ValueError('ZIP 清单与当前清单不一致')
                elif not path.is_file() or content!=path.read_bytes():
                    raise ValueError('ZIP 与当前文件不一致：'+relative)
    except (ValueError,KeyError,TypeError,OSError,zipfile.BadZipFile,RuntimeError,EOFError,zlib.error,NotImplementedError) as exc:
        errors.append(str(exc))
    return {'passed':not errors,'errors':errors}


def require(root,subtree,identity):
    result=inspect(root,subtree,identity)
    if not result['passed']:
        raise ValueError('素材完整性检查失败：'+'；'.join(result['errors']))
