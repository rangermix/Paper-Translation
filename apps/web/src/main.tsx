import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ErrorNotice, Icon } from './components';
import { useResource, useRoute } from './hooks';
import { DocumentDetail, Library } from './features/library';
import { UploadPage } from './features/upload';
import { Jobs, PreflightPage } from './features/workflow';
import { Editor } from './features/editor';
import { Glossaries, Memories, Search, Settings } from './features/knowledge';
import { HistoryPage } from './features/history';
import type { Capability, Preferences } from './types';
import './styles.css';
const navigation = [{ page: 'library', label: '文档库', icon: 'book' }, { page: 'upload', label: '上传 PDF', icon: 'upload' }, { page: 'jobs', label: '任务中心', icon: 'tasks' }, { page: 'search', label: '全文检索', icon: 'search' }, { page: 'glossary', label: '术语表', icon: 'terms' }, { page: 'memory', label: '个人翻译记忆', icon: 'memory' }, { page: 'settings', label: '设置', icon: 'settings' }];
function App() {
  const route = useRoute(); const capabilities = useResource<Capability>('/capabilities'); const preferences = useResource<Preferences>('/settings/preferences'); const [menu, setMenu] = useState(false);
  useEffect(() => { setMenu(false); }, [route.page, route.id]);
  useEffect(() => { if (preferences.data?.theme) document.documentElement.dataset.theme = preferences.data.theme; }, [preferences.data?.theme]);
  const label = navigation.find(n => n.page === route.page)?.label ?? ({ documents: '文档详情', preflight: '解析结果', drafts: '译文编辑', history: '版本历史' }[route.page] ?? '文档库');
  let content;
  switch (route.page) {
    case 'upload': content = <UploadPage capability={capabilities.data}/>; break;
    case 'documents': content = route.id ? <DocumentDetail id={route.id} capability={capabilities.data}/> : <Library/>; break;
    case 'jobs': content = <Jobs id={route.id}/>; break;
    case 'preflight': content = route.id ? <PreflightPage id={route.id}/> : <Library/>; break;
    case 'drafts': content = route.id ? <Editor key={route.id} id={route.id}/> : <Library/>; break;
    case 'history': content = route.id ? <HistoryPage id={route.id}/> : <Library/>; break;
    case 'glossary': content = <Glossaries/>; break;
    case 'memory': content = <Memories/>; break;
    case 'search': content = <Search/>; break;
    case 'settings': content = <Settings onTheme={theme => { document.documentElement.dataset.theme = theme; preferences.reload(); }}/>; break;
    default: content = <Library/>;
  }
  return <><a className="skip-link" href="#main">跳到主要内容</a>{menu && <button className="menu-scrim" aria-label="关闭导航" onClick={() => setMenu(false)}/>}<aside className={`sidebar ${menu ? 'open' : ''}`} aria-label="主要导航"><a className="brand" href="#/library"><span className="brand-icon"><Icon name="book"/></span><span>对照文库<small>BILINGUAL LIBRARY</small></span></a><button className="icon-btn mobile-close" aria-label="关闭菜单" onClick={() => setMenu(false)}><Icon name="close"/></button><nav>{navigation.map(n => <a className="nav-item" key={n.page} href={`#/${n.page}`} aria-current={route.page === n.page || n.page === 'library' && ['documents', 'history', 'drafts', 'preflight'].includes(route.page) ? 'page' : undefined}><Icon name={n.icon}/>{n.label}</a>)}</nav><div className="side-bottom"><p>个人 PDF 知识库</p><p>本地保存 · 静态阅读</p><a href="#/settings">查看运行与配置状态</a></div></aside><div className="shell"><header className="topbar"><div className="stack"><button className="icon-btn mobile-menu" aria-label="打开菜单" aria-expanded={menu} onClick={() => setMenu(m => !m)}><Icon name="menu"/></button><div className="breadcrumb">个人知识库 <span> / {label}</span></div><span className="mobile-title">对照文库</span></div><a className="topbar-action" href="#/upload"><Icon name="upload"/> 上传 PDF</a></header><main className="main" id="main"><ErrorNotice error={capabilities.error} retry={capabilities.reload}/>{content}</main></div></>;
}
createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
