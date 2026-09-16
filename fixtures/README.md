# 人工合成测试资料

`sample.pdf` 是一页人工生成的PDF，`sample-document-v3.json`是相应人工编写的完整类型IR；不是Docling解析输出，也不是机器翻译结果。所有PDF locator来自生成时已知坐标。`figure.png`对应PDF内原图。

它们只用于内部契约校验与受控 PDF 上传测试，不提供 IR 上传入口。`import-pdf.json` 和 `provider-output.json` 是接口样例；真实应用通过解析器处理上传的 PDF，测试夹具不替代实际解析或模型输出。
