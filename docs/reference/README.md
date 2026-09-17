# 阅读样式与旧版资料

[`res/reference/reader-v1.css`](../../res/reference/reader-v1.css)逐字节保留已提供的样式。`res/reference/reference-files.sha256.json`列出相对于 `res/` 的路径与哈希；两篇受控论文、原 PDF 和配图位于 `res/reference/legacy/`。这些文件供生产维护命令 `seed-legacy` 与解析回归测试使用，不是独立应用入口。

2026-09-16 清理时仅移动文件并更新清单路径，原文、译读页面、PDF、图片及阅读样式的字节哈希保持不变。导入时按 `legacy-manifest.json` 将目录导航替换为应用根路径；直接打开原始种子 HTML 不作为产品阅读入口。单文件导出由生产导出服务生成。

2026-09-17 目录调整将运行时资料归入根目录 `res/`。清单、PDF、页面、图片和 CSS 均保留原字节；清单内旧 `reference/` 路径按 `res/` 解析，不重写历史产物。

所有旧译读说明保留。旧页面不是严格原文/翻译准确性金标准；全文正式翻译必须从PDF重新走M1。这里是受控参考资料，不提供任意HTML导入。
