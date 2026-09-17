"""BUILD-TIME ONLY: retrieve pinned model files and verify every byte against the lock."""
import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def main():
    cli=argparse.ArgumentParser();cli.add_argument('--destination',required=True);cli.add_argument('--lock',default='deployment/parser-models.lock.json');args=cli.parse_args()
    root=Path(args.destination);lock=json.loads(Path(args.lock).read_text('utf-8'))
    for repo in lock['repositories']:
        for entry in repo['files']:
            target=root/repo['local_directory']/entry['path'];target.parent.mkdir(parents=True,exist_ok=True)
            base=repo.get('download_base','https://huggingface.co/'+repo['repo_id']+'/resolve/'+repo['revision']+'/')
            url=base+entry['path']
            sha=hashlib.sha256();count=0
            with urllib.request.urlopen(url,timeout=120) as response,target.with_suffix(target.suffix+'.tmp').open('wb') as handle:
                while chunk:=response.read(1024*1024):
                    count+=len(chunk)
                    if count>entry['byte_size']:raise ValueError('Model file exceeds locked size')
                    sha.update(chunk);handle.write(chunk)
            if count!=entry['byte_size'] or sha.hexdigest()!=entry['sha256']:raise ValueError('Model hash mismatch')
            target.with_suffix(target.suffix+'.tmp').replace(target)
    (root/'verified-lock.json').write_text(json.dumps(lock,sort_keys=True,separators=(',',':')),encoding='utf-8')


if __name__=='__main__':main()
