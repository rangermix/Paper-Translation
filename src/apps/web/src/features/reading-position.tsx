import { ErrorNotice } from '../components';
import { resourceId } from '../domain';
import { useResource } from '../hooks';

export type ReadingPosition = {
  generation: number;
  document_id: string;
  locale: string;
  artifact_id: string;
  block_id: string | null;
  offset: number;
  current_artifact: boolean;
  current_artifact_id: string | null;
  migration_required?: boolean;
  migration_notice?: string | null;
  previous_position?: { artifact_id: string; block_id: string; offset: number } | null;
};

export function positionPath(documentId: string, locale: string, artifactId: string) {
  return `/reading-position?${new URLSearchParams({ document_id: documentId, locale, artifact_id: artifactId })}`;
}

export function PositionNotice({ position }: { position: ReadingPosition }) {
  if (!position.migration_required) return null;
  const previous = position.previous_position ?? (!position.current_artifact && position.block_id ? position : null);
  return <div className="field-note warn" role="status">
    <strong>阅读位置属于另一个版本</strong>
    <p>请在当前版本中手动选择段落以保存新位置。系统没有把旧位置自动迁移到当前版本。</p>
    <div className="stack">
      {previous && <a href={`/artifacts/${resourceId(previous.artifact_id)}/index.html#b-${resourceId(previous.block_id!)}`} target="_blank" rel="noreferrer">查看旧版阅读位置</a>}
      {position.current_artifact_id && !position.current_artifact && <a href={`/artifacts/${resourceId(position.current_artifact_id)}/index.html`} target="_blank" rel="noreferrer">打开当前阅读版本</a>}
    </div>
  </div>;
}

export function EditionReadingPosition({ documentId, locale, artifactId }: { documentId: string; locale: string; artifactId: string }) {
  const result = useResource<ReadingPosition>(positionPath(documentId, locale, artifactId));
  const position = result.data?.artifact_id === artifactId && result.data.document_id === documentId && result.data.locale === locale ? result.data : undefined;
  return <>
    <ErrorNotice error={result.error} retry={result.reload}/>
    {position && <PositionNotice position={position}/>}
    {position?.current_artifact && !position.migration_required && position.block_id && <a className="btn sm" href={`/artifacts/${resourceId(artifactId)}/index.html#b-${resourceId(position.block_id)}`} target="_blank" rel="noreferrer">继续阅读已保存段落</a>}
  </>;
}
