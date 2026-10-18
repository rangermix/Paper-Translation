import { Modal } from '../components';
import { useNavigationGuard } from '../navigation-guard';

/** Creating a source draft and confirming a new source remain separate explicit steps. */
export function useSourceLeaveProtection(dirty: boolean, busy: boolean) {
  const guard = useNavigationGuard(dirty || busy);
  const request = async (action: () => void) => { if (await guard.request()) action(); };
  const dialog = guard.requested ? <Modal title="有未保存的校对输入" busy={busy} onClose={() => guard.resolve(false)}>
    <p>文字、理由或修正选项尚未提交。继续校对后，可按原有步骤创建草稿并确认新来源。</p>
    <div className="stack">
      <button className="btn primary" disabled={busy} onClick={() => guard.resolve(false)}>继续校对</button>
      <button className="btn" disabled={busy} onClick={() => guard.resolve(true)}>放弃输入</button>
    </div>
  </Modal> : null;
  return { request, dialog };
}
