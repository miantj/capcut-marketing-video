#!/usr/bin/env python3
"""Read-only installed draft/index/path checks; does not verify native UI."""
import argparse,json
from pathlib import Path

def check(draft,store):
    draft,store=Path(draft).resolve(),Path(store).resolve();errors=[]
    def read(p):
        try:return json.loads(p.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError) as e:errors.append(f'{p}: {e}');return {}
    content=read(draft/'draft_content.json');meta=read(draft/'draft_meta_info.json');index=read(store/'root_meta_info.json')
    info=draft/'draft_info.json'
    if info.exists() and read(info)!=content:errors.append('Diverged draft_info/content: select latest native timeline before claiming installation is current')
    ident=content.get('id');entries=[e for e in index.get('all_draft_store',[]) if e.get('draft_id')==ident] if ident else []
    if len(entries)!=1:errors.append(f'Expected one index entry for draft ID, got {len(entries)}')
    def resolve(value):
        import re
        match=re.fullmatch(r'##_draftpath_placeholder_(.+?)_##/(.*)',value)
        if match:
            if match.group(1).casefold()!=str(ident).casefold():
                errors.append('Foreign draft placeholder: '+value)
                return draft/'__unresolved_foreign_draft__'
            return (draft/match.group(2)).resolve()
        p=Path(value);return (p if p.is_absolute() else draft/p).resolve()
    for label,obj in [('metadata',meta)]+[('index',e) for e in entries]:
        if obj.get('draft_id')!=ident:errors.append(f'{label}: identity mismatch')
        if obj.get('draft_name')!=content.get('name'):errors.append(f'{label}: name mismatch')
        for field,expected in [('draft_fold_path',draft),('draft_root_path',store)]:
            if not obj.get(field) or resolve(obj[field])!=expected:errors.append(f'{label}: wrong {field}')
        f=obj.get('draft_json_file','')
        if not f or resolve(f).parent!=draft or not resolve(f).is_file():errors.append(f'{label}: invalid timeline path')
        if obj.get('draft_is_invisible') or obj.get('tm_draft_removed',0):errors.append(f'{label}: hidden or removed')
    materials={m.get('id'):m for group in content.get('materials',{}).values() if isinstance(group,list) for m in group if isinstance(m,dict)}
    registered={resolve(m['file_Path']) for g in meta.get('draft_materials',[]) for m in g.get('value',[]) if m.get('file_Path')}
    media=set();counts={}
    for track in content.get('tracks',[]):
        counts[track.get('type','unknown')]=counts.get(track.get('type','unknown'),0)+len(track.get('segments',[]))
        for seg in track.get('segments',[]):
            mat=materials.get(seg.get('material_id'),{});value=mat.get('path')
            if value:
                path=resolve(value);media.add(str(path))
                if not path.is_file():errors.append(f'Missing media: {path}')
                if path not in registered:errors.append(f'Unregistered media: {path}')
    if not content.get('tracks'):errors.append('No editable timeline tracks')
    return dict(ok=not errors,draft=str(draft),store=str(store),name=content.get('name'),id=ident,canvas=content.get('canvas_config'),segments_by_type=counts,media_count=len(media),errors=errors,native_ui_verified=False)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--draft',required=True);p.add_argument('--store',required=True);a=p.parse_args();r=check(a.draft,a.store);print(json.dumps(r,ensure_ascii=False,indent=2));raise SystemExit(0 if r['ok'] else 1)
