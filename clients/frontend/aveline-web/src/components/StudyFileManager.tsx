import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Folder, FileText, Save, Edit2, Eye, RefreshCw, 
  ChevronRight, ChevronDown, Plus, Trash2, File,
  Loader2, AlertCircle, Check
} from 'lucide-react';
import { api } from '../api/apiService';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

// Types
interface FileItem {
  name: string;
  type: 'file' | 'dir';
  size?: number;
  mtime?: number;
}

interface FileListResponse {
  path: string;
  items: FileItem[];
}

export const StudyFileManager: React.FC = () => {
  const [currentPath, setCurrentPath] = useState('/');
  const [files, setFiles] = useState<FileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Editor State
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState('');
  const [originalContent, setOriginalContent] = useState(''); // Check for changes
  const [isEditing, setIsEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Initial Load
  useEffect(() => {
    fetchFiles(currentPath);
  }, [currentPath]);

  const fetchFiles = async (path: string) => {
    setLoading(true);
    setError(null);
    try {
      const effectivePath = path === '/' ? '.' : path;
      
      const res = await api.runStudyTool('study_data', 'manage', {
        action: 'list',
        path: effectivePath
      });
      
      let data: FileListResponse | null = null;
      if (typeof res === 'string') {
        try {
          data = JSON.parse(res) as FileListResponse;
        } catch {
          data = null;
        }
      } else if (res && res.status === 'success' && res.data) {
        data = res.data as FileListResponse;
      } else {
        data = res as FileListResponse;
      }

      if (res && res.status === 'error') {
        setError(res.message || 'Failed to load files');
        setFiles([]);
        return;
      }

      if (data && Array.isArray(data.items)) {
        // Sort: Directories first, then files
        const sorted = data.items.sort((a, b) => {
          if (a.type === b.type) return a.name.localeCompare(b.name);
          return a.type === 'dir' ? -1 : 1;
        });
        setFiles(sorted);
      } else {
        // Handle empty or error
        setFiles([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load files");
    } finally {
      setLoading(false);
    }
  };

  const handleFileClick = async (item: FileItem) => {
    if (item.type === 'dir') {
      const newPath = currentPath === '/' ? item.name : `${currentPath}/${item.name}`;
      setCurrentPath(newPath);
    } else {
      // Read file
      const filePath = currentPath === '/' ? item.name : `${currentPath}/${item.name}`;
      setSelectedFile(filePath);
      setIsEditing(false); // Default to view mode
      await readFile(filePath);
    }
  };

  const readFile = async (path: string) => {
    setLoading(true);
    try {
      const res = await api.runStudyTool('study_data', 'manage', {
        action: 'read_text',
        path: path
      });
      // Response is content string directly usually
      // But if error, it might be JSON
      let content = '';
      if (typeof res === 'object' && res.status === 'error') {
        setError(res.message);
        content = '';
      } else if (typeof res === 'object' && res.status === 'success') {
        content = typeof res.data === 'string' ? res.data : JSON.stringify(res.data, null, 2);
      } else {
        content = typeof res === 'string' ? res : JSON.stringify(res, null, 2);
      }
      
      setFileContent(content);
      setOriginalContent(content);
    } catch (err) {
      setError("Failed to read file");
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!selectedFile) return;
    setSaving(true);
    try {
      const res = await api.runStudyTool('study_data', 'manage', {
        action: 'write_text',
        path: selectedFile,
        content: fileContent
      });

      if (res && (res.written || (res.status === 'success' && res.data?.written))) {
        setOriginalContent(fileContent);
        setSaveSuccess(true);
        setTimeout(() => setSaveSuccess(false), 2000);
        setIsEditing(false);
      } else {
        setError("Failed to save: " + (res.message || "Unknown error"));
      }
    } catch (err) {
      setError("Failed to save file");
    } finally {
      setSaving(false);
    }
  };

  const handleGoUp = () => {
    if (currentPath === '/') return;
    const parts = currentPath.split('/');
    parts.pop();
    const newPath = parts.join('/') || '/';
    setCurrentPath(newPath);
  };

  return (
    <div className="flex h-[calc(100vh-180px)] gap-4 text-emerald-100">
      {/* Sidebar: File List */}
      <div className="w-1/3 min-w-[250px] bg-black/20 rounded-xl border border-emerald-500/20 flex flex-col overflow-hidden">
        {/* Path Header */}
        <div className="p-3 bg-emerald-500/10 border-b border-emerald-500/20 flex items-center gap-2">
          <button 
            onClick={handleGoUp}
            disabled={currentPath === '/'}
            className="p-1 hover:bg-emerald-500/20 rounded disabled:opacity-30 transition-colors"
          >
            <ChevronDown className="rotate-90" size={16} />
          </button>
          <div className="text-xs font-mono truncate flex-1 opacity-70" title={currentPath}>
            {currentPath}
          </div>
          <button 
            onClick={() => fetchFiles(currentPath)}
            className="p-1 hover:bg-emerald-500/20 rounded transition-colors"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </button>
        </div>

        {/* File List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1 scrollbar-thin scrollbar-thumb-emerald-500/20">
          {error && (
            <div className="p-2 text-xs text-red-400 bg-red-500/10 rounded border border-red-500/20 flex items-center gap-2">
              <AlertCircle size={12} />
              {error}
            </div>
          )}
          
          {files.map((item) => (
            <motion.div
              key={item.name}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              onClick={() => handleFileClick(item)}
              className={`flex items-center gap-2 p-2 rounded cursor-pointer transition-all text-sm group
                ${selectedFile?.endsWith(item.name) && item.type === 'file' 
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' 
                  : 'hover:bg-white/5 border border-transparent'
                }
              `}
            >
              {item.type === 'dir' ? (
                <Folder size={16} className="text-emerald-400 shrink-0" />
              ) : (
                <FileText size={16} className="text-emerald-200/60 shrink-0" />
              )}
              <span className="truncate flex-1">{item.name}</span>
              {item.type === 'dir' && (
                <ChevronRight size={14} className="opacity-0 group-hover:opacity-50" />
              )}
            </motion.div>
          ))}

          {files.length === 0 && !loading && (
            <div className="text-center py-8 text-white/20 text-xs">
              Folder is empty
            </div>
          )}
        </div>
      </div>

      {/* Main: Editor/Viewer */}
      <div className="flex-1 bg-black/20 rounded-xl border border-emerald-500/20 flex flex-col overflow-hidden relative">
        {selectedFile ? (
          <>
            {/* Toolbar */}
            <div className="h-12 flex items-center justify-between px-4 bg-emerald-500/10 border-b border-emerald-500/20">
              <div className="flex items-center gap-2">
                <File size={16} className="text-emerald-400" />
                <span className="text-sm font-medium">{selectedFile.split('/').pop()}</span>
                {fileContent !== originalContent && (
                  <span className="text-[10px] bg-yellow-500/20 text-yellow-300 px-1.5 py-0.5 rounded border border-yellow-500/30">
                    Modified
                  </span>
                )}
              </div>
              
              <div className="flex items-center gap-2">
                {isEditing ? (
                  <>
                    <button 
                      onClick={() => setIsEditing(false)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/5 hover:bg-white/10 transition-colors"
                    >
                      <Eye size={14} />
                      Preview
                    </button>
                    <button 
                      onClick={handleSave}
                      disabled={saving || fileContent === originalContent}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                      Save
                    </button>
                  </>
                ) : (
                  <button 
                    onClick={() => setIsEditing(true)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/5 hover:bg-white/10 transition-colors"
                  >
                    <Edit2 size={14} />
                    Edit
                  </button>
                )}
              </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-hidden relative">
              {isEditing ? (
                <textarea
                  value={fileContent}
                  onChange={(e) => setFileContent(e.target.value)}
                  className="w-full h-full bg-black/40 p-4 text-sm font-mono text-emerald-100/90 resize-none focus:outline-none focus:ring-1 focus:ring-emerald-500/30"
                  spellCheck={false}
                />
              ) : (
                <div className="h-full overflow-y-auto p-6 scrollbar-thin scrollbar-thumb-emerald-500/20">
                  <div className="prose prose-invert prose-emerald max-w-none prose-pre:bg-black/30 prose-pre:border prose-pre:border-emerald-500/20">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm, remarkMath]}
                      rehypePlugins={[rehypeKatex]}
                      components={{
                        code({node, inline, className, children, ...props}: any) {
                          const match = /language-(\w+)/.exec(className || '')
                          return !inline && match ? (
                            <SyntaxHighlighter
                              style={oneDark}
                              language={match[1]}
                              PreTag="div"
                              {...props}
                            >
                              {String(children).replace(/\n$/, '')}
                            </SyntaxHighlighter>
                          ) : (
                            <code className={className} {...props}>
                              {children}
                            </code>
                          )
                        }
                      }}
                    >
                      {fileContent}
                    </ReactMarkdown>
                  </div>
                </div>
              )}

              {/* Success Toast */}
              <AnimatePresence>
                {saveSuccess && (
                  <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 20 }}
                    className="absolute bottom-6 right-6 bg-emerald-500 text-black px-4 py-2 rounded-lg shadow-lg shadow-emerald-500/20 flex items-center gap-2 text-xs font-bold"
                  >
                    <Check size={14} />
                    Saved Successfully
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-white/20 gap-3">
            <FileText size={48} className="opacity-20" />
            <p className="text-sm">Select a file to view or edit</p>
          </div>
        )}
      </div>
    </div>
  );
};
