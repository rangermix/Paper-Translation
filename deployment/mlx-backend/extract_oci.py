from pathlib import Path
import tarfile,json,io,hashlib,sys
source,target=Path(sys.argv[1]),Path(sys.argv[2])
target.mkdir()
with tarfile.open(source) as archive:
 def blob(digest):
  data=archive.extractfile('blobs/'+digest.replace(':','/')).read()
  assert hashlib.sha256(data).hexdigest()==digest.split(':')[1]
  return data
 index=json.load(archive.extractfile('index.json')); descriptor=index['manifests'][0]
 manifest=json.loads(blob(descriptor['digest']))
 if 'manifests' in manifest:
  descriptor=next(x for x in manifest['manifests'] if x.get('platform',{}).get('os')=='darwin')
  manifest=json.loads(blob(descriptor['digest']))
 config=json.loads(blob(manifest['config']['digest']))
 assert config['os']=='darwin' and config['architecture']=='arm64',config
 for layer in manifest['layers']:
  with tarfile.open(fileobj=io.BytesIO(blob(layer['digest']))) as contents: contents.extractall(target,filter='data')
 print(json.dumps({'manifest':descriptor['digest'],'config':config,'layers':manifest['layers']},indent=2))
