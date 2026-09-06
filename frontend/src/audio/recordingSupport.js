const CANDIDATE_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
];

/**
 * Detect a MediaRecorder MIME type this browser can actually record.
 * Returns null when WebM/Opus (or WebM) is unavailable.
 */
export function detectSupportedRecordingType() {
  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) {
    return null;
  }

  for (const type of CANDIDATE_TYPES) {
    if (MediaRecorder.isTypeSupported(type)) {
      return type;
    }
  }

  return null;
}

export function extensionForMime(mimeType) {
  if (!mimeType) return "webm";
  if (mimeType.includes("webm")) return "webm";
  if (mimeType.includes("ogg")) return "ogg";
  if (mimeType.includes("mp4")) return "m4a";
  return "webm";
}

export const MIN_DURATION_MS = 1000;
export const MAX_DURATION_MS = 60_000;
export const MAX_FILE_BYTES = 5 * 1024 * 1024;
