import { useCallback, useEffect, useRef, useState } from "react";
import {
  MAX_DURATION_MS,
  MAX_FILE_BYTES,
  MIN_DURATION_MS,
  detectSupportedRecordingType,
  extensionForMime,
} from "../audio/recordingSupport.js";

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatDuration(ms) {
  return `${(ms / 1000).toFixed(1)} 秒`;
}

function buildDownloadName(mimeType) {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `meetup-recording-${stamp}.${extensionForMime(mimeType)}`;
}

export default function RecordPanel() {
  const mimeType = useRef(detectSupportedRecordingType());
  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const startedAtRef = useRef(0);
  const maxTimerRef = useRef(null);
  const tickTimerRef = useRef(null);
  const keepResultRef = useRef(true);
  const stoppingRef = useRef(false);
  const holdActiveRef = useRef(false);
  const startingRef = useRef(false);

  const [recording, setRecording] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [error, setError] = useState(null);
  const [clip, setClip] = useState(null);

  const releaseMicrophone = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  }, []);

  const clearTimers = useCallback(() => {
    if (maxTimerRef.current) {
      clearTimeout(maxTimerRef.current);
      maxTimerRef.current = null;
    }
    if (tickTimerRef.current) {
      clearInterval(tickTimerRef.current);
      tickTimerRef.current = null;
    }
  }, []);

  const revokeClipUrl = useCallback((current) => {
    if (current?.url) {
      URL.revokeObjectURL(current.url);
    }
  }, []);

  const finishRecording = useCallback(
    (keepResult) => {
      holdActiveRef.current = false;
      const recorder = mediaRecorderRef.current;

      if (!recorder) {
        if (streamRef.current) {
          releaseMicrophone();
        }
        startingRef.current = false;
        setRecording(false);
        return;
      }

      if (stoppingRef.current) {
        return;
      }

      keepResultRef.current = keepResult;
      stoppingRef.current = true;
      clearTimers();

      if (recorder.state !== "inactive") {
        try {
          recorder.requestData?.();
          recorder.stop();
        } catch {
          releaseMicrophone();
          setRecording(false);
          stoppingRef.current = false;
          startingRef.current = false;
          setError("结束录音失败，请重试。");
        }
      } else {
        releaseMicrophone();
        setRecording(false);
        stoppingRef.current = false;
        startingRef.current = false;
      }
    },
    [clearTimers, releaseMicrophone]
  );

  const handleRecorderStop = useCallback(() => {
    const durationMs = Date.now() - startedAtRef.current;
    const type = mimeType.current || "audio/webm";
    const blob = new Blob(chunksRef.current, { type });
    chunksRef.current = [];
    mediaRecorderRef.current = null;

    releaseMicrophone();
    clearTimers();
    setRecording(false);
    setElapsedMs(durationMs);
    stoppingRef.current = false;
    startingRef.current = false;

    if (!keepResultRef.current) {
      setError(null);
      return;
    }

    if (durationMs < MIN_DURATION_MS) {
      setError("录音时长需至少 1 秒，请按住按钮重新录制。");
      return;
    }

    if (durationMs > MAX_DURATION_MS + 500) {
      setError("录音时长不能超过 60 秒，请重新录制。");
      return;
    }

    if (blob.size <= 0) {
      setError("未采集到有效音频，请重新录制。");
      return;
    }

    if (blob.size > MAX_FILE_BYTES) {
      setError("录音文件超过 5MB，请缩短说话时间后重试。");
      return;
    }

    const url = URL.createObjectURL(blob);
    setClip((prev) => {
      revokeClipUrl(prev);
      return {
        blob,
        url,
        mimeType: type,
        sizeBytes: blob.size,
        durationMs: Math.min(durationMs, MAX_DURATION_MS),
        fileName: buildDownloadName(type),
      };
    });
    setError(null);
  }, [clearTimers, releaseMicrophone, revokeClipUrl]);

  const startRecording = useCallback(async () => {
    if (recording || startingRef.current || stoppingRef.current) {
      return;
    }

    if (!mimeType.current) {
      holdActiveRef.current = false;
      setError("当前浏览器不支持 WebM/Opus 录音，请更换 Chrome、Edge 等浏览器后重试。");
      return;
    }

    startingRef.current = true;
    setError(null);

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      startingRef.current = false;
      holdActiveRef.current = false;
      if (err && (err.name === "NotAllowedError" || err.name === "PermissionDeniedError")) {
        setError("麦克风授权被拒绝，请在浏览器设置中允许本站使用麦克风后再试。");
      } else if (err && err.name === "NotFoundError") {
        setError("未检测到可用麦克风，请连接设备后重试。");
      } else {
        setError("无法打开麦克风，请检查设备权限后重试。");
      }
      return;
    }

    if (!holdActiveRef.current) {
      stream.getTracks().forEach((track) => track.stop());
      startingRef.current = false;
      return;
    }

    let recorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType: mimeType.current });
    } catch {
      stream.getTracks().forEach((track) => track.stop());
      startingRef.current = false;
      holdActiveRef.current = false;
      setError("无法开始录音，请更换浏览器后重试。");
      return;
    }

    if (!holdActiveRef.current) {
      stream.getTracks().forEach((track) => track.stop());
      startingRef.current = false;
      return;
    }

    streamRef.current = stream;
    mediaRecorderRef.current = recorder;
    chunksRef.current = [];
    keepResultRef.current = true;
    stoppingRef.current = false;
    startedAtRef.current = Date.now();
    setElapsedMs(0);
    setRecording(true);

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        chunksRef.current.push(event.data);
      }
    };

    recorder.onerror = () => {
      clearTimers();
      releaseMicrophone();
      setRecording(false);
      stoppingRef.current = false;
      startingRef.current = false;
      holdActiveRef.current = false;
      setError("录制过程出错，请重新尝试。");
    };

    recorder.onstop = handleRecorderStop;

    try {
      recorder.start(250);
    } catch {
      releaseMicrophone();
      setRecording(false);
      stoppingRef.current = false;
      startingRef.current = false;
      holdActiveRef.current = false;
      setError("启动录音失败，请重试。");
      return;
    }

    startingRef.current = false;

    if (!holdActiveRef.current) {
      finishRecording(true);
      return;
    }

    tickTimerRef.current = setInterval(() => {
      setElapsedMs(Date.now() - startedAtRef.current);
    }, 200);

    maxTimerRef.current = setTimeout(() => {
      finishRecording(true);
    }, MAX_DURATION_MS);
  }, [
    recording,
    clearTimers,
    finishRecording,
    handleRecorderStop,
    releaseMicrophone,
  ]);

  useEffect(() => {
    const endHold = () => {
      if (!holdActiveRef.current && !mediaRecorderRef.current && !startingRef.current) {
        return;
      }
      finishRecording(true);
    };

    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        finishRecording(false);
      }
    };

    window.addEventListener("pointerup", endHold);
    window.addEventListener("pointercancel", endHold);
    window.addEventListener("blur", endHold);
    window.addEventListener("keydown", onKeyDown);

    return () => {
      window.removeEventListener("pointerup", endHold);
      window.removeEventListener("pointercancel", endHold);
      window.removeEventListener("blur", endHold);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [finishRecording]);

  useEffect(() => {
    return () => {
      clearTimers();
      releaseMicrophone();
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        try {
          mediaRecorderRef.current.stop();
        } catch {
          // ignore unmount cleanup errors
        }
      }
      setClip((prev) => {
        revokeClipUrl(prev);
        return null;
      });
    };
  }, [clearTimers, releaseMicrophone, revokeClipUrl]);

  const onPointerDown = (event) => {
    if (event.button !== undefined && event.button !== 0) {
      return;
    }
    event.preventDefault();
    holdActiveRef.current = true;
    startRecording();
  };

  const unsupported = !mimeType.current;

  return (
    <section className="record-panel">
      <p className="record-hint">
        按住按钮说话，松开结束。最短 1 秒，最长 60 秒，文件不超过 5MB。
        录音中可按 Esc 取消，或点「取消录音」。
      </p>

      {unsupported ? (
        <p className="status error" role="alert">
          当前浏览器不支持 WebM/Opus 录音，请更换 Chrome、Edge 等浏览器。
        </p>
      ) : (
        <p className="status muted">将使用格式：{mimeType.current}</p>
      )}

      <button
        type="button"
        className={`record-button${recording ? " recording" : ""}`}
        disabled={unsupported}
        onPointerDown={onPointerDown}
        onContextMenu={(event) => event.preventDefault()}
        aria-pressed={recording}
      >
        {recording ? `录音中 ${formatDuration(elapsedMs)}` : "按住 说话"}
      </button>

      {recording ? (
        <button
          type="button"
          className="cancel-button"
          onClick={() => finishRecording(false)}
        >
          取消录音
        </button>
      ) : null}

      {error ? (
        <p className="status error" role="alert">
          {error}
        </p>
      ) : null}

      {clip ? (
        <div className="clip-panel">
          <h2>本地试听</h2>
          <p className="status muted">
            时长 {formatDuration(clip.durationMs)} · 大小{" "}
            {formatBytes(clip.sizeBytes)} · {clip.mimeType}
          </p>
          <audio controls src={clip.url} />
          <p>
            <a href={clip.url} download={clip.fileName}>
              下载录音文件（供后续上传接口测试）
            </a>
          </p>
        </div>
      ) : null}
    </section>
  );
}
