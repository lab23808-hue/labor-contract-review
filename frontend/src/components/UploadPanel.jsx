import { useState } from "react";

// 当前后端 DocumentParser 真正实现了的格式只有 .txt
// （parser/document_parser.py 里 PdfParser/DocxParser/OcrParser 都是占位类，
// parse_bytes 直接抛 NotImplementedError）。这里不凭空放开 pdf/docx/图片。
const SUPPORTED_EXTENSIONS = [".txt"];
const UNSUPPORTED_FORMAT_MESSAGE = "当前 MVP 暂不支持该文件格式，请上传支持的合同文件。";

function isSupportedFile(file) {
  const name = file.name.toLowerCase();
  return SUPPORTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

/**
 * UploadPanel：合同库侧边栏顶部的"新建合同"小部件。
 * 只负责"选文件 + 上传"，不做任何合同解析逻辑，也不关心上传成功之后
 * 页面要跳到哪——那是 App 通过 onUpload 决定的。
 */
export default function UploadPanel({ onUpload, loading }) {
  const [selectedFile, setSelectedFile] = useState(null);
  const [formatError, setFormatError] = useState(null);

  function handleFileChange(event) {
    const file = event.target.files?.[0] ?? null;
    setFormatError(null);
    setSelectedFile(null);

    if (!file) return;

    if (!isSupportedFile(file)) {
      setFormatError(UNSUPPORTED_FORMAT_MESSAGE);
      event.target.value = "";
      return;
    }

    setSelectedFile(file);
  }

  function handleSubmit() {
    if (!selectedFile || loading) return; // 防止重复提交
    onUpload(selectedFile);
    setSelectedFile(null);
  }

  return (
    <div className="upload-panel">
      <label className="upload-file-label">
        <input
          type="file"
          accept={SUPPORTED_EXTENSIONS.join(",")}
          onChange={handleFileChange}
          disabled={loading}
        />
      </label>
      {formatError && <p className="error-text">{formatError}</p>}
      {selectedFile && !formatError && <p className="hint-text">已选择：{selectedFile.name}</p>}

      <button type="button" onClick={handleSubmit} disabled={!selectedFile || loading}>
        {loading ? "上传中..." : "+ 新建合同"}
      </button>
    </div>
  );
}
