// 端侧摄像头监控 hook：使用 @mediapipe/tasks-vision 的 FaceDetector 在浏览器本地检测。
// 隐私原则：绝不采集/上传原始画面、音频；只输出结构化观察（presence/activity/confidence/signals）。
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Observation } from '../types/focusSession';

// MediaPipe 模型与 WASM 均改为本地加载（public/models、public/wasm），避免依赖境外 CDN。
// 模型文件来自官方 mediapipe-models bucket 的 blaze_face_short_range.tflite（float16 版）。
const MODEL_URL = `${import.meta.env.BASE_URL ?? '/'}models/blaze_face_short_range.tflite`;
const WASM_PATH = `${import.meta.env.BASE_URL ?? '/'}wasm`;

// 检测节流：每 DETECT_INTERVAL_MS 一次（3~5s 足以判断状态，且 CPU 占用低）
const DETECT_INTERVAL_MS = 4000;

type PermissionState = 'idle' | 'requesting' | 'granted' | 'denied' | 'unsupported' | 'inuse';

export interface CameraMonitorOptions {
  // 每产出一条观察回调（带 sequence）
  onObservation?: (obs: Observation) => void;
  // 摄像头被拒绝/拔出/不可用时回调
  onError?: (msg: string) => void;
  enabled?: boolean;
}

export function useCameraMonitor(opts: CameraMonitorOptions = {}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const detectorRef = useRef<any>(null);
  const rafRef = useRef<number | null>(null);
  const seqRef = useRef(0);
  const lastDetectRef = useRef(0);
  const runningRef = useRef(false);
  const distractionCounterRef = useRef(0);

  const [permission, setPermission] = useState<PermissionState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [previewOn, setPreviewOn] = useState(false);

  const emit = useCallback(
    (presence: Observation['presence'], activity: Observation['activity'], confidence: number, signals: string[]) => {
      const now = Math.floor(Date.now() / 1000);
      seqRef.current += 1;
      const obs: Observation = {
        sequence: seqRef.current,
        observed_at: now,
        presence,
        activity,
        confidence,
        signals,
        page_visible: typeof document !== 'undefined' ? !document.hidden : true,
        client_ts: now,
      };
      opts.onObservation?.(obs);
    },
    [opts],
  );

  const detectOnce = useCallback(() => {
    const detector = detectorRef.current;
    const video = videoRef.current;
    if (!detector || !video || video.readyState < 2) return;
    try {
      const now = performance.now();
      const result = detector.detectForVideo(video, now);
      const detections = result?.detections ?? [];
      if (detections.length === 0) {
        distractionCounterRef.current += 1;
        // 连续多次无人脸才判定 away（避免检测抖动误判）
        const presence: Observation['presence'] = distractionCounterRef.current >= 2 ? 'away' : 'unknown';
        emit(presence, 'unknown', 0.0, ['no_face']);
        return;
      }
      distractionCounterRef.current = 0;
      // 用 bounding box 中心与画面中心的偏移判断姿态
      const d = detections[0];
      const bbox = d.boundingBox; // {originX, originY, width, height}
      const cx = (bbox.originX + bbox.width / 2);
      const cy = (bbox.originY + bbox.height / 2);
      const vw = video.videoWidth || 1;
      const vh = video.videoHeight || 1;
      const offsetX = Math.abs(cx / vw - 0.5) * 2; // 0(居中) ~ 1(边缘)
      const offsetY = Math.abs(cy / vh - 0.5) * 2;
      const offset = Math.max(offsetX, offsetY);
      const conf = d.categories?.[0]?.score ?? 0.85;
      const headAway = offset > 0.33;
      const activity: Observation['activity'] = headAway ? 'possibly_distracted' : 'focused';
      const signals: string[] = [];
      if (headAway) signals.push('head_away');
      emit('present', activity, conf, signals);
    } catch (e: any) {
      // 检测异常（遮挡/光照）按 unknown 处理，不指责
      emit('unknown', 'unknown', 0.0, ['detect_error']);
    }
  }, [emit]);

  const loop = useCallback(() => {
    if (!runningRef.current) return;
    const now = performance.now();
    if (now - lastDetectRef.current >= DETECT_INTERVAL_MS) {
      lastDetectRef.current = now;
      detectOnce();
    }
    rafRef.current = requestAnimationFrame(loop);
  }, [detectOnce]);

  const stop = useCallback(() => {
    runningRef.current = false;
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    setPreviewOn(false);
  }, []);

  const start = useCallback(async () => {
    if (runningRef.current) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setPermission('unsupported');
      setError('当前环境不支持摄像头（需 HTTPS 或 localhost）');
      opts.onError?.('unsupported');
      return;
    }
    setPermission('requesting');
    try {
      // 懒加载 MediaPipe（动态 import，避免影响首屏）
      if (!detectorRef.current) {
        const vision = await import('@mediapipe/tasks-vision');
        const fileset = await vision.FilesetResolver.forVisionTasks(WASM_PATH);
        detectorRef.current = await vision.FaceDetector.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: MODEL_URL, delegate: 'GPU' },
          runningMode: 'VIDEO',
        });
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 480 }, height: { ideal: 270 }, facingMode: 'user' },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
      setPermission('granted');
      setPreviewOn(true);
      runningRef.current = true;
      lastDetectRef.current = 0;
      rafRef.current = requestAnimationFrame(loop);
    } catch (e: any) {
      const name = e?.name || '';
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        setPermission('denied');
        setError('摄像头权限被拒绝');
      } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
        setPermission('denied');
        setError('未找到可用摄像头');
      } else if (name === 'NotReadableError') {
        setPermission('inuse');
        setError('摄像头被其他程序占用');
      } else {
        setPermission('denied');
        setError(`摄像头启动失败：${e?.message || e}`);
      }
      opts.onError?.(error || 'camera_error');
      runningRef.current = false;
    }
  }, [loop, opts, error]);

  // 标签页隐藏时不检测（Page Visibility）
  useEffect(() => {
    const onVis = () => {
      if (document.hidden && runningRef.current) {
        // 上报一次 page_visible=false，便于后端感知掉线
        emit('unknown', 'unknown', 0.0, ['page_hidden']);
      }
    };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, [emit]);

  useEffect(() => () => stop(), [stop]);

  return { videoRef, start, stop, permission, error, previewOn };
}
