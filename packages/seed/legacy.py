"""Compose maintenance-only seeds: two release-known pages, never arbitrary HTML."""
import base64
import hashlib
import mimetypes
import re
from pathlib import Path
from sqlalchemy import select
from packages.domain.db import lock_singleton,writable
from packages.domain.errors import require
from packages.domain.models import SourceAsset,Document,Edition,Artifact,Publication
from packages.ir import canonical_bytes,digest,strict_loads
from packages.publisher import verify_artifact
from packages.storage import atomic_write,safe_path

ROOT=Path(__file__).resolve().parents[2]
RELEASE_MANIFEST_HASH='487013ade690a5766252f123dddf9f457b99759be15bb08e70d5631735ccb810'


def checked_release():
    release=strict_loads((ROOT/'reference/legacy-manifest.json').read_bytes())
    require(digest(release)==RELEASE_MANIFEST_HASH,'LEGACY_MANIFEST_INVALID')
    reference=strict_loads((ROOT/'reference/reference-files.sha256.json').read_bytes())
    require(len(release['documents'])==2 and {d['id'] for d in release['documents']}=={'legacy-efficient','legacy-pathways'},'LEGACY_MANIFEST_INVALID')
    for item in release['documents']:
        outputs={entry['output']:entry for entry in item['files']}
        require(len(outputs)==len(item['files']) and outputs.get('legacy-original.html',{}).get('path')==item['html_path']
            and outputs.get(item['source_output'],{}).get('path')==item['source_path'],'LEGACY_MANIFEST_INVALID')
        for entry in item['files']:
            require(reference.get(entry['path'])==entry['sha256'],'LEGACY_HASH_NOT_ALLOWED')
            file=safe_path(ROOT,entry['path'],must_exist=True)
            require(digest(file.read_bytes())==entry['sha256'],'LEGACY_HASH_MISMATCH')
    css=(ROOT/'reference/reader-v1.css').read_bytes()
    require(digest(css)==release['reader_css_sha256']==reference['reference/reader-v1.css'],'TEMPLATE_HASH_MISMATCH')
    return release


def seed_legacy(db,cfg):
    release=checked_release();created=0;outcomes=[]
    for item in release['documents']:
        with db.transaction() as session:
            writable(session);lock_singleton(session)
            previous=session.get(Document,item['id'])
            if previous:
                outcomes.append({'document_id':previous.id,'status':'deleted' if previous.deleted_at else 'already_seeded'})
                continue
            files={}
            for entry in item['files']:
                content=safe_path(ROOT,entry['path'],must_exist=True).read_bytes()
                require(digest(content)==entry['sha256'],'LEGACY_HASH_MISMATCH')
                files[entry['output']]=content
            original=files['legacy-original.html']
            before,after=release['navigation_patch']['from'].encode(),release['navigation_patch']['to'].encode()
            require(original.count(before)==1,'LEGACY_NAVIGATION_MISMATCH')
            page=original.replace(before,after,1)
            files['index.html']=page;files['reader.css']=(ROOT/'reference/reader-v1.css').read_bytes()
            script_hashes=[base64.b64encode(hashlib.sha256(script).digest()).decode() for script in re.findall(rb'<script[^>]*>(.*?)</script>',page,re.S)]
            csp="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; script-src "+' '.join("'sha256-"+h+"'" for h in script_hashes)+"; connect-src 'none'; base-uri 'none'; object-src 'none'; form-action 'none'"
            manifest={'schema_version':'1.0','legacy':True,'mode':'release','document_id':item['id'],'target_locale':'zh-Hans',
                'template_id':'reader-v1','template_sha256':release['reader_css_sha256'],'renderer_version':'legacy-copy-v1','renderer_sha256':digest(Path(__file__).read_bytes()),
                'source_snapshot_hash':None,'translation_snapshot_hash':None,'qa_fingerprint':None,'include_source':True,
                'original_pdf_path':item['source_output'],'legacy_source_path':item['html_path'],'legacy_original_sha256':digest(original),
                'navigation_patch':release['navigation_patch'],'content_security_policy':csp,
                'notice':'Legacy curated reading; no precise block provenance or certified source/translation alignment. Original page notice retained.',
                'files':[{'path':name,'byte_size':len(content),'sha256':digest(content),'media_type':mimetypes.guess_type(name)[0] or 'application/octet-stream'} for name,content in sorted(files.items())]}
            manifest['content_digest']=digest(manifest['files'])
            aid=item['id']+'-artifact-v1';key=f'documents/{item["id"]}/artifacts/{aid}'
            for name,content in files.items():atomic_write(cfg.data,key+'/'+name,content)
            atomic_write(cfg.data,key+'/manifest.json',canonical_bytes(manifest))
            verify_artifact(safe_path(cfg.data,key))
            pdf=files[item['source_output']];pdf_sha=digest(pdf)
            asset=session.scalar(select(SourceAsset).where(SourceAsset.sha256==pdf_sha))
            if asset is None:
                asset_id=item['id']+'-source';source_key=f'sources/{asset_id}/original.pdf'
                atomic_write(cfg.data,source_key,pdf)
                asset=SourceAsset(id=asset_id,sha256=pdf_sha,byte_size=len(pdf),page_count=item['page_count'],storage_key=source_key)
                session.add(asset);session.flush()
            document=Document(id=item['id'],title=item['title'],source_asset_id=asset.id,source_language='en',status='published')
            session.add(document);session.flush()
            edition=Edition(id=item['id']+'-zh-Hans',document_id=document.id,target_locale='zh-Hans',generation=2,current_artifact_id=aid)
            session.add(edition);session.flush()
            artifact=Artifact(id=aid,document_id=document.id,edition_id=edition.id,source_revision_id=None,translation_revision_id=None,template_id='reader-v1',storage_key=key,manifest_hash=digest(manifest),state='verified',legacy=True)
            session.add(artifact);session.flush()
            session.add(Publication(id=item['id']+'-initial-publication',edition_id=edition.id,artifact_id=aid,generation=2,operation='seed_legacy',origin='migration'))
            outcomes.append({'document_id':document.id,'artifact_id':aid,'status':'seeded','legacy':True});created+=1
    return {'created':created,'documents':outcomes}
